from __future__ import absolute_import, division, print_function, unicode_literals

import torch
import torch.nn as nn

from transformers import GPT2PreTrainedModel
from transformers.modeling_bert import BertLayerNorm as LayerNorm
from transformers.modeling_gpt2 import Block

from models.detector_feature import SimpleDetector
from models.pytorch_misc import pack_sequence, pad_sequence

import numpy as np 

import pickle
import ipdb
import math
import pandas
import random

class Causal_intervention(nn.Module):
    def __init__(self, config):
        super(Causal_intervention, self).__init__()
        
        
        self.z1_img = self.init_parameter('/workspace/visual-comet/models/conf_image_80_768.pkl')
        self.z1_evt = self.init_parameter('/workspace/visual-comet/models/evt_bert_100.pkl')
        self.z1_plc = self.init_parameter('/workspace/visual-comet/models/place_80_by_150.pkl')

        
        self.init_linear_layers(config)

    def init_parameter(self, file_path):
        with open(file_path, 'rb') as f:
            conf = pickle.load(f)
        conf_array = np.array(conf)
        return nn.Parameter(torch.from_numpy(conf_array).cuda().to(torch.float32).requires_grad_())

    def init_linear_layers(self, config):
        self.z1_k = nn.Linear(768, config.n_embd)
        self.z1_v = nn.Linear(768, config.n_embd)
        self.z2_k = nn.Linear(768, config.n_embd)
        self.z2_v = nn.Linear(768, config.n_embd)
        self.evt_k = nn.Linear(768, config.n_embd)
        self.evt_v = nn.Linear(768, config.n_embd)
        self.s_q1 = nn.Linear(config.n_embd, config.n_embd)
        self.s_q2 = nn.Linear(config.n_embd, config.n_embd)
        self.s_q3 = nn.Linear(config.n_embd, config.n_embd)

    def forward(self, x): 


         #evt
        evt = self.evt_k(self.z1_evt)
        att_S = torch.matmul(x, torch.t(evt))/ math.sqrt(x.size(-1))
        att_S = nn.Softmax(dim=-1)(att_S)
        S = torch.matmul(att_S, self.evt_v(self.z1_evt))
        
        att_causal_evt = self.s_q1(S)  #train 

        #plc
        plc = self.z2_k(self.z1_plc)
        att_S = torch.matmul(x, torch.t(plc))/ math.sqrt(x.size(-1))
        att_S = nn.Softmax(dim=-1)(att_S)
        S = torch.matmul(att_S, self.z2_v(self.z1_plc))
        
        att_causal_plc = self.s_q2(S)

        #img
        img = self.z1_k(self.z1_img) # z1_img : [80, 768] -> [768, 768]
        att_S = torch.matmul(x, torch.t(img))/ math.sqrt(x.size(-1)) # x : [32, 128, 768] z1 : [768, 768]
        att_S = nn.Softmax(dim=-1)(att_S)
        S = torch.matmul(att_S, self.z1_v(self.z1_img))
        
        att_causal_img = self.s_q3(S)
        
        final_causal_att = torch.zeros_like(att_causal_evt)
        
        for i in range(len(att_causal_evt)):
            num = random.choice([0,1,2])
            if num == 0 :
                final_causal_att[i] = att_causal_evt[i]
            elif num == 2 :
                final_causal_att[i] = att_causal_img[i]
            else :
                final_causal_att[i] = att_causal_plc[i]
        '''
        tmp = []
        final_causal_att = torch.zeros_like(att_causal_evt)
        for i in range(len(att_causal_evt)): #batch
            for j in range(len(att_causal_evt[0])) : #128
                tmp1 = 0.4   * att_causal_evt[i][j] #len = 768 #
                tmp2 = 0.2 * att_causal_plc[i][j]
                tmp3 = 0.4 * att_causal_img[i][j]
                
                final_causal_att[i][j] = tmp1+tmp2+tmp3 
        '''        
        #ipdb.set_trace()

        return final_causal_att

class GPT2VisionAttentiveTransformer(GPT2PreTrainedModel):
    def __init__(self, config):
        super(GPT2VisionAttentiveTransformer, self).__init__(config)
        self.output_hidden_states = config.output_hidden_states
        self.output_attentions = config.output_attentions

        self.wte = nn.Embedding(config.vocab_size, config.n_embd)
        self.wpe = nn.Embedding(config.n_positions, config.n_embd)
        self.drop = nn.Dropout(config.embd_pdrop)
        self.h = nn.ModuleList([Block(config.n_ctx, config, scale=True) for _ in range(config.n_layer)])
        self.ln_f = LayerNorm(config.n_embd, eps=config.layer_norm_epsilon)

        self.use_person_ids = config.use_person_ids
        self.use_subject_ids = config.use_subject_ids
        if self.use_subject_ids:
            self.subject_embed = nn.Embedding(2, embedding_dim=config.n_embd)

        self.init_weights()

        self.detector = SimpleDetector(pretrained=True, final_dim=config.n_embd, use_bbox=config.use_bbox)

        #causal
        
        self.causal_att = Causal_intervention(config)
        self.ln_causal = LayerNorm(config.n_embd, eps=config.layer_norm_epsilon)

    def _resize_token_embeddings(self, new_num_tokens):
        """
        Wrapper around PreTrainedModel._get_resized_embeddings

        Resize input token embeddings matrix of the model if new_num_tokens != config.vocab_size.

        New number of tokens in the embedding matrix. Increasing the size will add newly initialized vectors at the end. Reducing the size will remove vectors from the end.
        """
        self.wte = self._get_resized_embeddings(self.wte, new_num_tokens)
        return self.wte

    def _prune_heads(self, heads_to_prune):
        """ Prunes heads of the model.
            heads_to_prune: dict of {layer_num: list of heads to prune in this layer}
        """
        for layer, heads in heads_to_prune.items():
            self.h[layer].attn.prune_heads(heads)

    def forward(self, input_ids,
                position_ids=None,
                token_type_ids=None,
                past=None,
                head_mask=None,
                img_feats=None,
                boxes=None,
                boxes_mask=None,
                objects=None,
                segments=None,
                person_ids=None,
                subject_ids=None
                ):
        if past is None:
            past_length = 0
            past = [None] * len(self.h)
        else:
            past_length = past[0][0].size(-2)
        if position_ids is None:
            position_ids = torch.arange(past_length, input_ids.size(-1) + past_length, dtype=torch.long, device=input_ids.device)
            position_ids = position_ids.unsqueeze(0).expand_as(input_ids)

        # Prepare head mask if needed
        # 1.0 in head_mask indicate we keep the head
        # attention_probs has shape bsz x n_heads x N x N
        # head_mask has shape n_layer x batch x n_heads x N x N
        if head_mask is not None:
            if head_mask.dim() == 1:
                head_mask = head_mask.unsqueeze(0).unsqueeze(0).unsqueeze(-1).unsqueeze(-1)
                head_mask = head_mask.expand(self.config.n_layer, -1, -1, -1, -1)
            elif head_mask.dim() == 2:
                head_mask = head_mask.unsqueeze(1).unsqueeze(-1).unsqueeze(-1)  # We can specify head_mask for each layer
            head_mask = head_mask.to(dtype=next(self.parameters()).dtype) # switch to fload if need + fp16 compatibility
        else:
            head_mask = [None] * self.config.n_layer

        input_shape = input_ids.size()
        input_ids = input_ids.view(-1, input_ids.size(-1))
        position_ids = position_ids.view(-1, position_ids.size(-1))

        inputs_embeds = self.wte(input_ids)

        if img_feats is not None:
            # For each instance in a batch. position 0 is a special token indicating start of
            # visual features. Position 1 onwards are reserved for visual features.
            # inputs_embeds[: 1: num_max_boxes, :] --> `num_max_boxes` is an setting in VCRDataset
            vision_output = self.detector(img_feats=img_feats, boxes=boxes, box_mask=boxes_mask, obj_labels=objects)
            vision_embeddings = vision_output['obj_reps']
            vision_obj_loss = vision_output['cnn_regularization_loss']
            if self.use_person_ids:
                pack_person_ids = pack_sequence(person_ids, boxes_mask)
                person_embeddings = self.wte(pack_person_ids)
                person_embeddings = pad_sequence(person_embeddings, boxes_mask.sum(1).tolist())
                vision_embeddings = vision_embeddings + person_embeddings
            if self.use_subject_ids:
                pack_subject_ids = pack_sequence(subject_ids, boxes_mask)
                subject_embeddings = self.subject_embed(pack_subject_ids)
                subject_embeddings = pad_sequence(subject_embeddings, boxes_mask.sum(1).tolist())
                vision_embeddings = vision_embeddings + subject_embeddings
            inputs_embeds[:, 1:vision_embeddings.size(1)+1, :] = vision_embeddings

        # if aux_feats is not None:
        #     inputs_embeds[:,169] = aux_feats

        position_embeds = self.wpe(position_ids)
        if token_type_ids is not None:
            token_type_ids = token_type_ids.view(-1, token_type_ids.size(-1))
            token_type_embeds = self.wte(token_type_ids)
        else:
            token_type_embeds = 0
        hidden_states = inputs_embeds + position_embeds + token_type_embeds
        hidden_states = self.drop(hidden_states)

        output_shape = input_shape + (hidden_states.size(-1),)

        presents = ()
        all_attentions = []
        all_hidden_states = ()
        for i, (block, layer_past) in enumerate(zip(self.h, past)):
            if self.output_hidden_states:
                all_hidden_states = all_hidden_states + (hidden_states.view(*output_shape),)

            outputs = block(hidden_states, layer_past, head_mask[i])
            hidden_states, present = outputs[:2]
            presents = presents + (present,)
            
            hidden_states = hidden_states + self.causal_att(hidden_states)

            if self.output_attentions:
                all_attentions.append(outputs[2])

        hidden_states = self.ln_f(hidden_states)

        #causal
        #hidden_states = hidden_states + self.causal_att(hidden_states)  # dimension ?
        #hidden_states = self.ln_causal(hidden_states)

        hidden_states = hidden_states.view(*output_shape)
        # Add last hidden state
        if self.output_hidden_states:
            all_hidden_states = all_hidden_states + (hidden_states,)

        outputs = (hidden_states, presents)
        if self.output_hidden_states:
            outputs = outputs + (all_hidden_states,)
        if self.output_attentions:
            # let the number of heads free (-1) so we can extract attention even after head pruning
            attention_output_shape = input_shape[:-1] + (-1,) + all_attentions[0].shape[-2:]
            all_attentions = tuple(t.view(*attention_output_shape) for t in all_attentions)
            outputs = outputs + (all_attentions,)
        if img_feats is not None:
            outputs = outputs + (vision_obj_loss, )
        return outputs  # last hidden state, presents, (all hidden_states), (attentions)


class GPT2VisionAttentiveLMHead(GPT2PreTrainedModel):
    def __init__(self, config):
        super(GPT2VisionAttentiveLMHead, self).__init__(config)
        self.transformer = GPT2VisionAttentiveTransformer(config)
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)

        self.init_weights()
        self.tie_weights()

    def tie_weights(self):
        """ Make sure we are sharing the input and output embeddings.
            Export to TorchScript can't handle parameter sharing so we are cloning them instead.
        """
        self._tie_or_clone_weights(self.lm_head,
                                   self.transformer.wte)

    def forward(self,
                input_ids,
                position_ids=None,
                token_type_ids=None,
                labels=None,
                past=None,
                head_mask=None,
                img_feats=None,
                boxes=None,
                boxes_mask=None,
                objects=None,
                segments=None,
                person_ids=None,
                subject_ids=None,
                use_rank=False,
                get_rationale=False
                ):

        transformer_outputs = self.transformer(input_ids,
                                               position_ids=position_ids,
                                               token_type_ids=token_type_ids,
                                               past=past,
                                               head_mask=head_mask,
                                               img_feats=img_feats,
                                               boxes=boxes,
                                               boxes_mask=boxes_mask,
                                               objects=objects,
                                               segments=segments,
                                               person_ids=person_ids,
                                               subject_ids=subject_ids
                                               )
        hidden_states = transformer_outputs[0]
        if get_rationale:
            return hidden_states[:,-1]
        lm_logits = self.lm_head(hidden_states)

        outputs = (lm_logits,) + transformer_outputs[1:]
        if labels is not None:
            # Shift so that tokens < n predict n
            shift_logits = lm_logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            # Flatten the tokens
            if use_rank:
                loss_fct = nn.CrossEntropyLoss(ignore_index=-1,reduce=False)
                loss = loss_fct(shift_logits.view(-1, shift_logits.size(-1)),
                                shift_labels.view(-1))
                loss = loss.view(lm_logits.size(0),-1)
                non_zeros = lm_logits.new_ones(lm_logits.size(0)) * lm_logits.size(1) - (loss == 0).sum(dim=1).float()
                loss = torch.sum(loss,dim=1)
                loss = torch.div(loss, non_zeros)
            else:
                loss_fct = nn.CrossEntropyLoss(ignore_index=-1)
                loss = loss_fct(shift_logits.view(-1, shift_logits.size(-1)),
                                shift_labels.view(-1))
            outputs = (loss,) + outputs

        return outputs  # (loss), lm_logits, presents, (all hidden_states), (attentions), (vision_loss)

    def _resize_token_embeddings(self, new_num_tokens):
        self.transformer.resize_token_embeddings(new_num_tokens)

            # from __future__ import absolute_import, division, print_function, unicode_literals

            # import torch
            # import torch.nn as nn

            # from transformers import GPT2PreTrainedModel
            # from transformers.modeling_bert import BertLayerNorm as LayerNorm
            # from transformers.modeling_gpt2 import Block

            # from models.detector_feature import SimpleDetector
            # from models.pytorch_misc import pack_sequence, pad_sequence

            # import numpy as np 

            # import pickle
            # import ipdb
            # import math
            # import pandas

            # class Causual_intervention(nn.Module): 
            #     def __init__(self, config):
            #         super(Causual_intervention, self).__init__()
                    
            #         with open('/workspace/je/vc-causal/models/conf_image_80_768.pkl','rb') as f :
            #             conf = pickle.load(f)
            #         conf_np = np.array(conf)
            #         #self.z1 = nn.Parameter(torch.from_numpy(np.load('/workspace/je/vc-causal/~')).cuda().to(torch.float32).requires_grad_())  #float32?
            #         self.z1 = nn.Parameter(torch.from_numpy(conf_np).cuda().to(torch.float32).requires_grad_()) 
            #         self.z1_k = nn.Linear(768, config.n_embd) ## edit
            #         self.z1_v = nn.Linear(768, config.n_embd)
            #         self.s_q = nn.Linear(config.n_embd, config.n_embd)

            #     def forward(self, x):
            #         #ipdb.set_trace()
                    
            #         z1 = self.z1_k(self.z1)
            #         att_S = torch.matmul(x, torch.t(z1))/ math.sqrt(x.size(-1))
            #         att_S = nn.Softmax(dim=-1)(att_S)
            #         S = torch.matmul(att_S, self.z1_v(self.z1))
                    
            #         att_causal = self.s_q(S)

            #         return att_causal

            # class GPT2VisionAttentiveTransformer(GPT2PreTrainedModel):
            #     def __init__(self, config):
            #         super(GPT2VisionAttentiveTransformer, self).__init__(config)
            #         self.output_hidden_states = config.output_hidden_states
            #         self.output_attentions = config.output_attentions

            #         self.wte = nn.Embedding(config.vocab_size, config.n_embd)
            #         self.wpe = nn.Embedding(config.n_positions, config.n_embd)
            #         self.drop = nn.Dropout(config.embd_pdrop)
            #         self.h = nn.ModuleList([Block(config.n_ctx, config, scale=True) for _ in range(config.n_layer)])
            #         self.ln_f = LayerNorm(config.n_embd, eps=config.layer_norm_epsilon)

            #         self.use_person_ids = config.use_person_ids
            #         self.use_subject_ids = config.use_subject_ids
            #         if self.use_subject_ids:
            #             self.subject_embed = nn.Embedding(2, embedding_dim=config.n_embd)

            #         self.init_weights()

            #         self.detector = SimpleDetector(pretrained=True, final_dim=config.n_embd, use_bbox=config.use_bbox)

            #         #causal
                    
            #         self.causal_att = Causual_intervention(config)

            #     def _resize_token_embeddings(self, new_num_tokens):
            #         """
            #         Wrapper around PreTrainedModel._get_resized_embeddings

            #         Resize input token embeddings matrix of the model if new_num_tokens != config.vocab_size.

            #         New number of tokens in the embedding matrix. Increasing the size will add newly initialized vectors at the end. Reducing the size will remove vectors from the end.
            #         """
            #         self.wte = self._get_resized_embeddings(self.wte, new_num_tokens)
            #         return self.wte

            #     def _prune_heads(self, heads_to_prune):
            #         """ Prunes heads of the model.
            #             heads_to_prune: dict of {layer_num: list of heads to prune in this layer}
            #         """
            #         for layer, heads in heads_to_prune.items():
            #             self.h[layer].attn.prune_heads(heads)

            #     def forward(self, input_ids,
            #                 position_ids=None,
            #                 token_type_ids=None,
            #                 past=None,
            #                 head_mask=None,
            #                 img_feats=None,
            #                 boxes=None,
            #                 boxes_mask=None,
            #                 objects=None,
            #                 segments=None,
            #                 person_ids=None,
            #                 subject_ids=None
            #                 ):
            #         if past is None:
            #             past_length = 0
            #             past = [None] * len(self.h)
            #         else:
            #             past_length = past[0][0].size(-2)
            #         if position_ids is None:
            #             position_ids = torch.arange(past_length, input_ids.size(-1) + past_length, dtype=torch.long, device=input_ids.device)
            #             position_ids = position_ids.unsqueeze(0).expand_as(input_ids)

            #         # Prepare head mask if needed
            #         # 1.0 in head_mask indicate we keep the head
            #         # attention_probs has shape bsz x n_heads x N x N
            #         # head_mask has shape n_layer x batch x n_heads x N x N
            #         if head_mask is not None:
            #             if head_mask.dim() == 1:
            #                 head_mask = head_mask.unsqueeze(0).unsqueeze(0).unsqueeze(-1).unsqueeze(-1)
            #                 head_mask = head_mask.expand(self.config.n_layer, -1, -1, -1, -1)
            #             elif head_mask.dim() == 2:
            #                 head_mask = head_mask.unsqueeze(1).unsqueeze(-1).unsqueeze(-1)  # We can specify head_mask for each layer
            #             head_mask = head_mask.to(dtype=next(self.parameters()).dtype) # switch to fload if need + fp16 compatibility
            #         else:
            #             head_mask = [None] * self.config.n_layer

            #         input_shape = input_ids.size()
            #         input_ids = input_ids.view(-1, input_ids.size(-1))
            #         position_ids = position_ids.view(-1, position_ids.size(-1))

            #         inputs_embeds = self.wte(input_ids)

            #         if img_feats is not None:
            #             # For each instance in a batch. position 0 is a special token indicating start of
            #             # visual features. Position 1 onwards are reserved for visual features.
            #             # inputs_embeds[: 1: num_max_boxes, :] --> `num_max_boxes` is an setting in VCRDataset
            #             vision_output = self.detector(img_feats=img_feats, boxes=boxes, box_mask=boxes_mask, obj_labels=objects)
            #             vision_embeddings = vision_output['obj_reps']
            #             vision_obj_loss = vision_output['cnn_regularization_loss']
            #             if self.use_person_ids:
            #                 pack_person_ids = pack_sequence(person_ids, boxes_mask)
            #                 person_embeddings = self.wte(pack_person_ids)
            #                 person_embeddings = pad_sequence(person_embeddings, boxes_mask.sum(1).tolist())
            #                 vision_embeddings = vision_embeddings + person_embeddings
            #             if self.use_subject_ids:
            #                 pack_subject_ids = pack_sequence(subject_ids, boxes_mask)
            #                 subject_embeddings = self.subject_embed(pack_subject_ids)
            #                 subject_embeddings = pad_sequence(subject_embeddings, boxes_mask.sum(1).tolist())
            #                 vision_embeddings = vision_embeddings + subject_embeddings
            #             inputs_embeds[:, 1:vision_embeddings.size(1)+1, :] = vision_embeddings

            #         # if aux_feats is not None:
            #         #     inputs_embeds[:,169] = aux_feats

            #         position_embeds = self.wpe(position_ids)
            #         if token_type_ids is not None:
            #             token_type_ids = token_type_ids.view(-1, token_type_ids.size(-1))
            #             token_type_embeds = self.wte(token_type_ids)
            #         else:
            #             token_type_embeds = 0
            #         hidden_states = inputs_embeds + position_embeds + token_type_embeds
            #         hidden_states = self.drop(hidden_states)

            #         output_shape = input_shape + (hidden_states.size(-1),)

            #         presents = ()
            #         all_attentions = []
            #         all_hidden_states = ()
            #         for i, (block, layer_past) in enumerate(zip(self.h, past)):
            #             if self.output_hidden_states:
            #                 all_hidden_states = all_hidden_states + (hidden_states.view(*output_shape),)

            #             outputs = block(hidden_states, layer_past, head_mask[i])
            #             hidden_states, present = outputs[:2]
            #             presents = presents + (present,)

            #             if self.output_attentions:
            #                 all_attentions.append(outputs[2])

            #         hidden_states = self.ln_f(hidden_states)

            #         #causal
            #         hidden_states = hidden_states + self.causal_att(hidden_states)  # dimension ?
            #         hidden_states = self.ln_f(hidden_states)

            #         hidden_states = hidden_states.view(*output_shape)
            #         # Add last hidden state
            #         if self.output_hidden_states:
            #             all_hidden_states = all_hidden_states + (hidden_states,)

            #         outputs = (hidden_states, presents)
            #         if self.output_hidden_states:
            #             outputs = outputs + (all_hidden_states,)
            #         if self.output_attentions:
            #             # let the number of heads free (-1) so we can extract attention even after head pruning
            #             attention_output_shape = input_shape[:-1] + (-1,) + all_attentions[0].shape[-2:]
            #             all_attentions = tuple(t.view(*attention_output_shape) for t in all_attentions)
            #             outputs = outputs + (all_attentions,)
            #         if img_feats is not None:
            #             outputs = outputs + (vision_obj_loss, )
            #         return outputs  # last hidden state, presents, (all hidden_states), (attentions)


            # class GPT2VisionAttentiveLMHead(GPT2PreTrainedModel):
            #     def __init__(self, config):
            #         super(GPT2VisionAttentiveLMHead, self).__init__(config)
            #         self.transformer = GPT2VisionAttentiveTransformer(config)
            #         self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)

            #         self.init_weights()
            #         self.tie_weights()

            #     def tie_weights(self):
            #         """ Make sure we are sharing the input and output embeddings.
            #             Export to TorchScript can't handle parameter sharing so we are cloning them instead.
            #         """
            #         self._tie_or_clone_weights(self.lm_head,
            #                                 self.transformer.wte)

            #     def forward(self,
            #                 input_ids,
            #                 position_ids=None,
            #                 token_type_ids=None,
            #                 labels=None,
            #                 past=None,
            #                 head_mask=None,
            #                 img_feats=None,
            #                 boxes=None,
            #                 boxes_mask=None,
            #                 objects=None,
            #                 segments=None,
            #                 person_ids=None,
            #                 subject_ids=None,
            #                 use_rank=False,
            #                 get_rationale=False
            #                 ):

            #         transformer_outputs = self.transformer(input_ids,
            #                                             position_ids=position_ids,
            #                                             token_type_ids=token_type_ids,
            #                                             past=past,
            #                                             head_mask=head_mask,
            #                                             img_feats=img_feats,
            #                                             boxes=boxes,
            #                                             boxes_mask=boxes_mask,
            #                                             objects=objects,
            #                                             segments=segments,
            #                                             person_ids=person_ids,
            #                                             subject_ids=subject_ids
            #                                             )
            #         hidden_states = transformer_outputs[0] #[5,76,768]
                    
            #         if get_rationale:
            #             return hidden_states[:,-1]
            #         lm_logits = self.lm_head(hidden_states) #[5,76,50317]
                
            #         outputs = (lm_logits,) + transformer_outputs[1:]

            #         if labels is not None:
            #             # Shift so that tokens < n predict n
            #             shift_logits = lm_logits[..., :-1, :].contiguous()
            #             shift_labels = labels[..., 1:].contiguous()
            #             # Flatten the tokens
            #             if use_rank:
            #                 loss_fct = nn.CrossEntropyLoss(ignore_index=-1,reduce=False)
            #                 loss = loss_fct(shift_logits.view(-1, shift_logits.size(-1)),
            #                                 shift_labels.view(-1))
            #                 loss = loss.view(lm_logits.size(0),-1)
            #                 non_zeros = lm_logits.new_ones(lm_logits.size(0)) * lm_logits.size(1) - (loss == 0).sum(dim=1).float()
            #                 loss = torch.sum(loss,dim=1)
            #                 loss = torch.div(loss, non_zeros)
            #             else:
            #                 loss_fct = nn.CrossEntropyLoss(ignore_index=-1)
            #                 loss = loss_fct(shift_logits.view(-1, shift_logits.size(-1)),
            #                                 shift_labels.view(-1))
            #             outputs = (loss,) + outputs

            #         return outputs  # (loss), lm_logits, presents, (all hidden_states), (attentions), (vision_loss)

            #     def _resize_token_embeddings(self, new_num_tokens):
            #         self.transformer.resize_token_embeddings(new_num_tokens)

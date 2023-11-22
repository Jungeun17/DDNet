# DDNet : Dynamic Debiasing Network for Visual Commonsense Generation 

Most of the codes in this repo are copied/modified from [VisualCOMET](https://github.com/jamespark3922/visual-comet)

## Downloading the data
Follow the instructions from [VisualCOMET](https://github.com/jamespark3922/visual-comet)


## Installation
Install the requirements.
```
pip install -r requirements.txt
```

## Train
Before training, you might want to create a separate directory to save your experiments and model checkpoints.
```
mkdir experiments
```

Then, begin trainin with the following command :
```
python run_ft_DDNET.py --data_dir /path/to/visualcomet_annotations/  --output_dir experiments/image_inference --max_seq_len 128 --per_gpu_train_batch_size 64 --overwrite_output_dir --num_train_epochs 5 --save_steps 10000 --learning_rate 5e-5
```

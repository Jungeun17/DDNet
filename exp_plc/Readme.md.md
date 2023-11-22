# Dynamic Debiasing Network for Visual Commonsense Generation

---

## Task

(참조 : [https://github.com/jamespark3922/visual-comet/blob/master/README.md#task](https://github.com/jamespark3922/visual-comet/blob/master/README.md#task) )

In **VisualCOMET**, we are interested in making three types of inferences given a still image:

- person's **intents** at present
- events **before** the image
- events **after** the image

![Untitled](Dynamic%20Debiasing%20Network%20for%20Visual%20Commonsense%20G%20ce08720bf73a484da876bca830067709/Untitled.png)

## Step 1. prepare

- visual-comet.zip파일 unzip 한 뒤 visual-comet 폴더로 이동

```python
cd visual-comet
```

- requirements 설치 (The following code was tested on Python3.6 and pytorch >= 1.2)

```python
pip install -r requirements.txt
```

## Step 2. data download

- Images and Object Detections

```python
cd data
```

visual-comet 폴더 안 → data 폴더로 이동. 

 [VCR website](https://visualcommonsense.com/download/) 웹페이지에서 아래 사진처럼 Images 다운로드. 

![Untitled](Dynamic%20Debiasing%20Network%20for%20Visual%20Commonsense%20G%20ce08720bf73a484da876bca830067709/Untitled%201.png)

다운로드 후 `vcr1imges.zip` 파일 unzip.

visual-comet폴더 안에 있는 `config.py` 파일 열어서, 다운로드한 ‘data/vcr1images/’의 경로를  `VCR_IMAGES_DIR=/path/to/vcr1images` 에 작성.

(예시)

![Untitled](Dynamic%20Debiasing%20Network%20for%20Visual%20Commonsense%20G%20ce08720bf73a484da876bca830067709/Untitled%202.png)

- Visual Features

아래 명령어로 visual-comet 폴더 안에 features 다운로드 후 압축 해제.

```python
wget [https://storage.googleapis.com/ai2-mosaic/public/visualcomet/features.zip](https://storage.googleapis.com/ai2-mosaic/public/visualcomet/features.zip)
```

‘visual-comet/features’경로를 위 (예시) 사진 처럼  `config.py`

파일 열어서, `VCR_FEATURES_DIR=/path/to/features/` 에 작성

- 추가 경로 설정

```python
cd visual-comet/models
```

models폴더 안에 있는 `model.py`과 `model_gen.py`파일을 열어서 아래 사진에 해당하는 부분 경로 visual-comet 폴더 있는 경로로 바꿔주기.

(빨간 동그라미 표시 부분만 바꿔주기)

![Untitled](Dynamic%20Debiasing%20Network%20for%20Visual%20Commonsense%20G%20ce08720bf73a484da876bca830067709/Untitled%203.png)

## Step 3. training the model

### (* 학습된 모델로 결과만 뽑고 싶다면 바로 Step4로 !)

- visual-comet 폴더 안에서 아래 command를 입력하면 training 코드 실행.

```python
CUDA_VISIBLE_DEVICES=0,1 python run_ft_DDNET.py --data_dir /path/to/visualcomet_annotations/  --output_dir experiments/ --max_seq_len 128 --per_gpu_train_batch_size 64 --overwrite_output_dir --num_train_epochs 10 --save_steps 10000 --learning_rate 5e-5
```

gpu는 최소 2개 이상 사용 필수, 

- -data_dir 에는 visual-comet/data/visualcomet 경로 작성,

--per_gpu_train_batch_size는 gpu용량에 맞게 조절 가능,

다 학습되면 학습된 모델 --output_dir experiments/ 에 자동 저장.

## Step 4. Generationg Inference Sentences

- visual-comet 폴더 안에서 아래 command를 입력하면 generation 코드 실행.

```python
CUDA_VISIBLE_DEVICES=0 python run_gen_original.py --data_dir /path/to/visualcomet_annotations/ --model_name_or_path experiments/checkpoint/ --split val --do_sample 0 --num_samples 1 
```

gpu 1개만 사용 필수,

‘experiments/checkpoint/에 미리 학습된 모델 저장되어 있음.

(Step 3에서 학습한 모델로 generation 하고 싶다면 ‘--model_name_or_path experiments/~’ 에 해당 모델 경로 지정. )

generation 다 완료되면 해당 모델 경로 폴더 안에 ‘`val_sample_0_num_1_top_k_0_top_p_0.9.json`

‘ 생성 완료.
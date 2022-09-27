
# Challenge

This challenge focusses on an ordinal classification problem of an audio dataset consisting of two types of audios: A sustained long vowel audio and an answer/read recording. To create the environment and install the dependencies:

```bash
  conda env create -f environment.yml
  conda activate challenge
```


For this challenge, 5 different approaches are taken.

## 1. Conv1D with MFCC Features

For this approach, a feature vector consisting of the mean of the mfcc values and delta mfcc values is used. After building the feature vector, we will use a Conv1D layer to process this input vector. 

## 2. Conv1D with MFCC Features and Some Additional Features

For this case, some additional features which may provide more valuable information will be used. To analyze the audio better, airflow insufficiency, aperiodicity, irregular vibration of vocal folds, signal perturbation, increased noise features will be extracted and will be added to the feature vector for this task. Therefore, we will be extracting maximum phonation time, maximum phonation time until voice break, fraction of locally unvoiced frames, number of voice breaks, degree of voice breaks,shimmer,jitter,f0,dfa and hnr values as additional features.

This feature selection method is inspired by the papers [Vocal markers from sustained phonation in Huntington’s Disease](https://arxiv.org/abs/2006.05365) and [Phonatory Dysfunction as a Preclinical Symptom of Huntington Disease](https://www.researchgate.net/publication/268791311_Phonatory_Dysfunction_as_a_Preclinical_Symptom_of_Huntington_Disease).

## 3. Conv2D with MFCC Spectograms For Answering/Reading Task

For this approach, we will use a Conv2d model to process the mfcc spectograms. We will only use the recordings answer/reading for this approach. The goal for using only one of these task types is to analyze how the models would behave when we use only one of them. The reason behind the selection of Conv2d is because features engineered on audio data such as spectrograms have marked resemblance to images, in which CNNs excel at recognizing.

## 4. Conv2D + Transformer with MFCC Spectograms For Answering/Reading 
For this model, we will be adding a transformer layer ot the network. Main idea is to feed Conv2D layer and transformer layer with the input feature maps and concatenate the output embeddings at a fully-connected layer. The reason why we will use a transformer is because of their excellent ability to interpret sequential data such as features of the audio waveform represented as a time series
## 5. Conv2D + Transformer with MFCC Spectograms For Both Sustanined Long Vowel and Answering/Reading Tasks
In this approach, we will be using both types of the recordings. Just like the Approach 4, we will be using 1 Conv2D layer and 1 transformer layer for input feature maps of the each type of the recordings. Then, we will concatenate the output embeddings at a fully-connected layer again. 
## Implementation Notes
Since I was limited with the resources such as RAM and drivers, I wasn't able to use data augmentation methods and more complicated networks. I also had to downsample the audios using a lower sample rate than 22050 Hz. Therefore, these implementations might return different results with a large dataset and a decent hardware resources.

Since we have a limited dataset, most of the approaches with the highly parameterized models such as Conv2d face the problem of overfitting. 
| Model            | Accuracy                                                              |
| ----------------- | ------------------------------------------------------------------ |
| Conv1D with MFCC | 0.25|
| Conv1D with MFCC + Additional Features | 0.24|
| Conv2D with MFCC for 1 input | 0.06 |
| Conv2D + Transformers with MFCC for 1 input | 0.03 |
| Conv2D + Transformers with MFCC for 2 inputs | 0.02 |


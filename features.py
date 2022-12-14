from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np
import parselmouth
import pysptk
from numba import jit, float32, int32, prange
from parselmouth import praat
from scipy.stats import entropy
from scipy.stats import skew, kurtosis
from shennong.audio import Audio
from shennong.postprocessor.delta import DeltaPostProcessor
from shennong.processor.mfcc import MfccProcessor
from shennong.processor.pitch import PitchProcessor, \
    PitchPostProcessor
from soundsig.sound import BioSound

from .base import SampleProcessor, AudioSample


class PraatVoiceFeatures(SampleProcessor):
    """Computes the various shimmer/jitter features using the parselmouth
    binding librairy. All the features are accessed through the API's
    `parselmouth.praat.call` function and some very specific parameters"""
    # the following lines are extracted from
    # https://github.com/drfeinberg/PraatScripts/blob/master/Measure%20Pitch%2C%20HNR%2C%20Jitter%2C%20and%20Shimmer.ipynb
    # the different parameters used are default (I think) and the effect of
    # each can be found
    # in the praat documentation (for local jitter for instance):
    # http://www.fon.hum.uva.nl/praat/manual/PointProcess__Get_jitter__local____.html
    F0_MIN, F0_MAX = 75, 500
    jitter_feats = {
        "local": ("Get jitter (local)", (0, 0, 0.0001, 0.02, 1.3)),
        "local_absolute": ("Get jitter (local, absolute)", (0, 0, 0.0001, 0.02,
                                                            1.3)),
        "rap": ("Get jitter (rap)", (0, 0, 0.0001, 0.02, 1.3)),
        "ppq5": ("Get jitter (ppq5)", (0, 0, 0.0001, 0.02, 1.3)),
        "ddp": ("Get jitter (ddp)", (0, 0, 0.0001, 0.02, 1.3)),
    }
    shimmer_feats = {
        "local": ("Get shimmer (local)", (0, 0, 0.0001, 0.02, 1.3, 1.6)),
        "local_dB": ("Get shimmer (local_dB)", (0, 0, 0.0001, 0.02, 1.3, 1.6)),
        "apq3": ("Get shimmer (apq3)", (0, 0, 0.0001, 0.02, 1.3, 1.6)),
        "apq5": ("Get shimmer (apq5)", (0, 0, 0.0001, 0.02, 1.3, 1.6)),
        "apq11": ("Get shimmer (apq11)", (0, 0, 0.0001, 0.02, 1.3, 1.6)),
        "dda": ("Get shimmer (dda)", (0, 0, 0.0001, 0.02, 1.3, 1.6))
    }
    INPUT_SAMPLING_RATE = 16000

    def process(self, sample: AudioSample) -> Dict:
        try:
            sound = parselmouth.Sound(sample.data,
                                      sample.rate)
            point_process = praat.call(sound,
                                       "To PointProcess (periodic, cc)",
                                       self.F0_MIN, self.F0_MAX)
            features = {"jitter": dict(), "shimmer": dict()}
            for featname, (call_name, args) in self.jitter_feats.items():
                features["jitter"][featname] = praat.call(
                    point_process, call_name, *args)

            for featname, (call_name, args) in self.shimmer_feats.items():
                features["shimmer"][featname] = praat.call(
                    [sound, point_process], call_name, *args)

            return features

        except parselmouth.PraatError as e:
            print(f"Sample {sample.name}, ({len(sample.data):d} "
                  f"samples): error {str(e)})")


class ModulationPowerSpectrumAnalysis(SampleProcessor):
    """
    Computes, for each annotated audio sample, the modulation power spectrum,
    and diverse statistics associated
    """
    INPUT_SAMPLING_RATE = 16000

    def __init__(self,
                 max_abs_temporal_modulation=200,
                 min_spectral_modulation=0,
                 max_spectral_modulation=10 * 10 ** (-3)):
        """
        """

        super().__init__()
        self.max_abs_temporal_modulation = max_abs_temporal_modulation
        self.min_spectral_modulation = min_spectral_modulation
        self.max_spectral_modulation = max_spectral_modulation

    def filter_mps(self, mps: np.ndarray, wf: np.ndarray, wt: np.ndarray):
        # making an array with data divided in windows
        frequency_modulations_clip = wf[(wf >= self.min_spectral_modulation) & (wf <= self.max_spectral_modulation)]
        temporal_modulations_clip = wt[
            (wt >= -self.max_abs_temporal_modulation)
            & (wt <= self.max_abs_temporal_modulation)]
        temporal_modulations_indexes = (
                                               wt >= -self.max_abs_temporal_modulation) & (
                                               wt <= self.max_abs_temporal_modulation)
        frequency_modulations_indexes = ((wf > self.min_spectral_modulation)
                                         & (wf <= self.max_spectral_modulation))
        mps = mps[frequency_modulations_indexes, :]
        mps = mps[:, temporal_modulations_indexes]
        return mps, frequency_modulations_clip, temporal_modulations_clip

    def process(self, sample_data: AudioSample) -> Dict[str, np.ndarray]:
        maxAmp = np.abs(sample_data.data.astype(float)).max()
        myBioSound = BioSound(
            soundWave=sample_data.data.astype(float) / maxAmp,
            fs=float(sample_data.rate),
            emitter='empty',
            calltype='empty')
        # spec_sample_rate: 1000 == 1frame per ms
        myBioSound.spectroCalc(
            spec_sample_rate=1000,
            freq_spacing=50,
            min_freq=0,
            max_freq=sample_data.rate / 2)
        myBioSound.mpsCalc(window=0.1, Norm=True)

        filtered_mps, mps_wf, mps_wt = self.filter_mps(mps=myBioSound.mps,
                                                       wf=myBioSound.wf,
                                                       wt=myBioSound.wt)
        return {'mps': filtered_mps, 'mps_wf': mps_wf, 'mps_wt': mps_wt}


class PraatHNR(SampleProcessor):
    INPUT_SAMPLING_RATE = 16000

    def process(self, sample: AudioSample) -> List[float]:
        try:
            sound = parselmouth.Sound(sample.data,
                                      sample.rate)
            harmonicity = praat.call(sound, "To Harmonicity (cc)", 0.01,
                                     75, 0.1, 1.0)
            hnr = praat.call(harmonicity, "Get mean", 0, 0)
            return hnr

        except parselmouth.PraatError as e:
            print("Sample %s, (%i samples): error %s)" %
                  (sample.name,
                   len(sample.data), str(e)))


class FundamentalFrequency(SampleProcessor):
    INPUT_SAMPLING_RATE = 16000
    """Computes the f0 array for a sound file"""

    def __init__(self, method="shennong", hop_size=5, min_freq=75, max_freq=300):
        """

        :param method: The engine used for the F0 computation
        :param hop_size: The window hop size (also called frame shift), in ms
        :param min_freq: The minimum boundary for f0 values
        :param max_freq: The maximum boundary for f0 values
        """
        if method not in ("praat", "rapt", "swipe", "shennong"):
            raise ValueError(
                "F0 method has to be either praat, rapt, swipe or shennong")
        self.method = method
        self.hop_size = hop_size
        self.min_freq = min_freq
        self.max_freq = max_freq

    def process(self, sample_data: AudioSample) -> np.ndarray:
        frames_hopsize = int(self.hop_size / 1000 * sample_data.rate)
        pitch_values = None
        if self.method == "praat":
            snd = parselmouth.Sound(sample_data.data, sample_data.rate)
            pitch_values = snd.to_pitch(
                time_step=self.hop_size / 1000,
                pitch_floor=float(self.min_freq),
                pitch_ceil=float(self.max_freq)).selected_array['frequency']
            # setting 0 values to NaN
            pitch_values[pitch_values == 0] = np.nan
        elif self.method == "rapt":
            pitch_values = pysptk.rapt(
                sample_data.data.astype(np.float32),
                fs=sample_data.rate,
                hopsize=frames_hopsize,
                min=self.min_freq,
                max=self.max_freq,
                otype="f0")
            # setting 0 values to NaN
            pitch_values[pitch_values == 0] = np.nan
        elif self.method == "swipe":
            pitch_values = pysptk.swipe(
                sample_data.data.astype(np.float64),
                fs=sample_data.rate,
                hopsize=frames_hopsize,
                min=self.min_freq,
                max=self.max_freq,
                otype="f0")
            # setting 0 values to NaN
            pitch_values[pitch_values == 0] = np.nan
        elif self.method == "shennong":
            pitch_options = {
                'sample_rate': sample_data.rate,
                'frame_shift': 0.01,
                'frame_length': 0.025,
                'min_f0': self.min_freq,
                'max_f0': self.max_freq
            }
            pitch_processor = PitchProcessor(**pitch_options)
            audio_data = Audio(sample_data.data, sample_data.rate)
            pitch_values = pitch_processor.process(audio_data)
            pitch_values = pitch_values.data[:, 1]
        return pitch_values


class AdvancedFundamentalFrequency(SampleProcessor):
    """
    Computes, for each annotated audio sample, the pitch,
    the Probability of Voicing (pov), the convolution between pitch and pov
    It's fully based on shennong
    """
    INPUT_SAMPLING_RATE = 16000

    def __init__(self, hop_size=5, min_freq=75, max_freq=300):
        """

        :param hop_size: The window hop size (also called frame shift), in ms
        :param min_freq: The minimum boundary for f0 values
        :param max_freq: The maximum boundary for f0 values
        """
        self.hop_size = hop_size
        self.min_freq = min_freq
        self.max_freq = max_freq

    def process(self, sample: AudioSample) -> Dict:
        pitch_options = {
            'sample_rate': sample.rate,
            'frame_shift': 0.01,
            'frame_length': 0.025,
            'min_f0': self.min_freq,
            'max_f0': self.max_freq
        }
        pitch_processor = PitchProcessor(**pitch_options)
        post_pitch_processor = PitchPostProcessor()
        audio_data = Audio(sample.data, sample.rate)
        pitch_values = pitch_processor.process(audio_data)
        post_pitch_values = post_pitch_processor.process(pitch_values)
        pov = np.abs(post_pitch_values.data[:, 0])
        pov = -5.2 + 5.4 * np.exp(7.5 * (pov - 1)) + 4.8 * pov - 2 * np.exp(
            -10 * pov)
        pov = 1 / (1 + np.exp(-pov))
        features_dict = {
            "pitch": pitch_values.data[:, 1],
            "pov": pov,
            "pitch_pov_prod": np.prod([pitch_values.data[:, 1], pov], axis=0)
        }
        return features_dict


class MFCCsMeanOfStd(SampleProcessor):
    """
    Computes, for each annotated audio sample, the mean of standard deviations for the 12
    first coefficients of the MFCCs and their deltas
    """
    INPUT_SAMPLING_RATE = 16000

    def __init__(self,
                 window_type='hanning',
                 low_freq=20,
                 high_freq=-100,
                 use_energy=False,
                 delta=True,
                 delta_delta=False):
        """

        :param window_type: Window type
        :param low_freq: The minimum boundary for f0 values
        :param high_freq: The maximum boundary for f0 values
        :param use_energy: Use Energy or C0 for MFCC computation
        """
        super().__init__()

        self.window_type = window_type
        self.low_freq = low_freq
        self.high_freq = high_freq
        self.use_energy = use_energy
        self.delta = delta
        self.delta_delta = delta_delta

    def process(self, sample: AudioSample) -> Dict:
        mfcc_options = {
            'window_type': self.window_type,
            'low_freq': self.low_freq,
            'high_freq': self.high_freq,
            'use_energy': self.use_energy,
            'sample_rate': sample.rate,
        }
        mfcc_processor = MfccProcessor(**mfcc_options)
        audio_data = Audio(sample.data, sample.rate)
        mfcc_values = mfcc_processor.process(audio_data)
        if self.delta and self.delta_delta:
            delta_processor = DeltaPostProcessor(order=2)
            delta_values = delta_processor.process(mfcc_values)
            nmfcc = mfcc_values.shape[1]
            features_dict = {
                "mfcc":
                    np.mean(np.std(mfcc_values.data, axis=0)),
                "delta_mfcc":
                    np.mean(
                        np.std(delta_values.data[:, nmfcc:2 * nmfcc].data,
                               axis=0)),
                "delta_delta_mfcc":
                    np.mean(np.std(delta_values.data[:, 2 * nmfcc:].data, axis=0)),
            }
            return features_dict

        elif self.delta and not self.delta_delta:
            delta_processor = DeltaPostProcessor(order=1)
            delta_values = delta_processor.process(mfcc_values)
            nmfcc = mfcc_values.shape[1]
            features_dict = {
                "mfcc":
                    np.mean(np.std(mfcc_values.data, axis=0)),
                "delta_mfcc":
                    np.mean(
                        np.std(delta_values.data[:, nmfcc:2 * nmfcc].data,
                               axis=0)),
            }
            return features_dict

        else:
            features_dict = {
                "mfcc": np.mean(np.std(mfcc_values.data, axis=0)),
            }
            return features_dict


class VocalTremorFeatures(SampleProcessor):
    INPUT_SAMPLING_RATE = 16000
    PRAAT_SCRIPT_PATH = Path(__file__).absolute().parent \
                        / Path("data/tremor2.07/tremor.praat")

    def process(self, sample: AudioSample) -> Dict:
        try:
            sound = parselmouth.Sound(sample.data,
                                      sample.rate)
            tremor_outputs = praat.run_file(
                sound,
                str(self.PRAAT_SCRIPT_PATH),
                "Analyis mode",
                0.015,
                60,
                350,
                0.03,
                0.3,
                0.01,
                0.35,
                0.14,
                "Envelope [To AmplitudeTier (period)]",
                1.5,
                15,
                0.01,
                0.15,
                0.01,
                0.01,
                capture_output=True)
            tremor_features = {}
            for el in tremor_outputs[1].split('\n'):
                if len(el.split(':')) > 1:
                    try:
                        tremor_features[el.split(':')[0]] = float(
                            el.split(':')[1].split()[0])
                    except Exception:
                        tremor_features[el.split(':')[0]] = None
            return tremor_features

        except parselmouth.PraatError as e:
            print(f"Sample {sample.name}, ({len(sample.data):d} samples): "
                  f"error {str(e)})")


class AperiodicityFeatures(SampleProcessor):
    INPUT_SAMPLING_RATE = 16000

    def process(self, sample_data: AudioSample) -> Dict:
        try:
            sound = parselmouth.Sound(sample_data.data,
                                      sample_data.rate)
            pitch = sound.to_pitch()
            pulses = parselmouth.praat.call([sound, pitch],
                                            "To PointProcess (cc)")
            voice_report_str = parselmouth.praat.call(
                [sound, pitch, pulses], "Voice report", 0.0, 0.0, 75, 600,
                1.3, 1.6, 0.03, 0.45)

            aperiodicity_features = {}
            for el in voice_report_str.split('\n'):
                if len(el.split(':')) > 1:
                    if 'Fraction of locally unvoiced frames' in el:
                        aperiodicity_features[
                            'Fraction of locally unvoiced frames'] = float(
                            el.split(':')[1].replace("%",
                                                     "").split('(')[0])
                    if 'Number of voice breaks' in el:
                        aperiodicity_features[
                            'Number of voice breaks'] = float(
                            el.split(':')[1])
                    if 'Degree of voice breaks' in el:
                        aperiodicity_features[
                            'Degree of voice breaks'] = float(
                            el.split(':')[1].replace("%",
                                                     "").split('(')[0])
            return aperiodicity_features

        except parselmouth.PraatError as e:
            print(f"Sample {sample_data.name}, ({len(sample_data.data):d} "
                  f"samples): error {str(e)})")


class RPDE(SampleProcessor):
    INPUT_SAMPLING_RATE = 22500

    def __init__(self,
                 dim: int,
                 tau: int,
                 epsilon: float,
                 tmax: Optional[int] = None):
        super().__init__()
        self.epsilon, self.tau, self.dim = epsilon, tau, dim
        self.tmax = tmax

    @staticmethod
    @jit(int32[:](float32[:, :], float32, int32), nopython=True)
    def recurrence_histogram(ts: np.ndarray, epsilon: float, t_max: int):
        """Numba implementation of the recurrence histogram described in
        http://www.biomedical-engineering-online.com/content/6/1/23

        :param ts: Time series of dimension (T,N)
        :param epsilon: Recurrence ball ball radius
        :param t_max: Maximum distance for return.
        Larger distances are not recorded. Set to -1 for infinite distance.
        """
        return_distances = np.zeros(len(ts), dtype=np.int32)
        for i in np.arange(len(ts)):
            # finding the first "out of ball" index
            first_out = len(ts)  # security
            for j in np.arange(i + 1, len(ts)):
                if 0 < t_max < j - i:
                    break
                d = np.linalg.norm(ts[i] - ts[j])
                if d > epsilon:
                    first_out = j
                    break

            # finding the first "back to the ball" index
            for j in np.arange(first_out + 1, len(ts)):
                if 0 < t_max < j - i:
                    break
                d = np.linalg.norm(ts[i] - ts[j])
                if d < epsilon:
                    return_distances[j - i] += 1
                    break
        return return_distances

    @staticmethod
    @jit(int32[:](float32[:, :], float32, int32), parallel=True, nopython=True)
    def parallel_recurrence_histogram(ts: np.ndarray, epsilon: float, t_max: int):
        """Parallelized implem of the recurrence histogram. Works the same,
        but adapted to parallelized computing (automatically done by Numba)."""
        return_distances = np.zeros(len(ts), dtype=np.int32)

        # this is the parallized loop
        for i in prange(len(ts)):
            # finding the first "out of ball" index
            first_out = len(ts)  # security
            for j in np.arange(i + 1, len(ts)):
                if 0 < t_max < j - i:
                    break
                d = np.linalg.norm(ts[i] - ts[j])
                if d > epsilon:
                    first_out = j
                    break

            # finding the first "back to the ball" index
            for j in np.arange(first_out + 1, len(ts)):
                if 0 < t_max < j - i:
                    break
                d = np.linalg.norm(ts[i] - ts[j])
                if d < epsilon:
                    return_distances[i] = j - i
                    break

        # building histogram, can't be parallel
        # (potential concurrent access to histogram items)
        distance_histogram = np.zeros(len(ts), dtype=np.int32)
        for i in np.arange(len(ts)):
            if return_distances[i] != 0:
                distance_histogram[return_distances[i]] += 1
        return distance_histogram

    @staticmethod
    def embed_time_series(data: np.ndarray, dim: int, tau: int):
        """Embeds the time series, tested against the pyunicorn implementation
        of that transform"""
        embed_points_nb = data.shape[0] - (dim - 1) * tau
        # embed_mask is of shape (embed_pts, dim)
        embed_mask = np.arange(embed_points_nb)[:, np.newaxis] + np.arange(dim)
        tau_offsets = np.arange(dim) * (tau - 1)  # shape (dim,1)
        embed_mask = embed_mask + tau_offsets
        return data[embed_mask]

    def process(self, sample_data: AudioSample) -> float:
        # converting the sound array to the right format
        # (RPDE expects the array to be floats in [-1,1]
        if sample_data.data.dtype == np.int16:
            data = (sample_data.data / (2 ** 16)).astype(np.float32)
        else:
            data = sample_data.data.astype(np.float32)

        # ??building the time series, and computing the recurrence histogram
        embedded_ts = self.embed_time_series(data, self.dim, self.tau)
        if self.tmax is None:
            rec_histogram = self.parallel_recurrence_histogram(embedded_ts,
                                                               self.epsilon,
                                                               -1)
            # tmax is the highest non-zero value in the histogram
            tmax_idx = np.argwhere(rec_histogram != 0).flatten()[-1]
        else:
            rec_histogram = self.parallel_recurrence_histogram(embedded_ts,
                                                               self.epsilon,
                                                               self.tmax)
            tmax_idx = self.tmax
        # culling the histogram at the tmax index
        culled_histogram = rec_histogram[:tmax_idx]

        # normalizing the histogram (to make it a probability)
        # and computing its entropy
        normalized_histogram = culled_histogram / culled_histogram.sum()
        histogram_entropy = entropy(normalized_histogram)
        return histogram_entropy / np.log(culled_histogram.size)


class DFA(SampleProcessor):
    """Computes the Detrented Fluctuation Analysis. Code stolen from
    https://github.com/dokato/dfa .
    Shouldn't be dependent on the input audio's encoding (int16 or float32)"""
    INPUT_SAMPLING_RATE = 22500

    def __init__(self, scale_boundaries: Tuple[float, float],
                 scale_density: float):
        super().__init__()
        self.scale_bound = scale_boundaries
        self.scale_density = scale_density

    @staticmethod
    def compute_rms(x: np.ndarray, scale: int):
        # making an array with data divided in windows
        shape = (x.shape[0] // scale, scale)
        x = np.lib.stride_tricks.as_strided(x, shape=shape)
        # vector of x-axis points to regression
        scale_ax = np.arange(scale)
        rms = np.zeros(x.shape[0])
        for e, xcut in enumerate(x):
            coeff = np.polyfit(scale_ax, xcut, 1)
            xfit = np.polyval(coeff, scale_ax)
            # detrending and computing RMS of each window
            rms[e] = np.sqrt(np.mean((xcut - xfit) ** 2))
        return rms

    def process(self, sample_data: AudioSample) -> float:
        data = sample_data.data
        # cumulative sum of data with substracted offset
        y = np.cumsum(data - np.mean(data))
        scale_exponents = np.arange(self.scale_bound[0], self.scale_bound[1],
                                    self.scale_density)
        scales = (10 ** scale_exponents).astype(np.int)
        fluct = np.zeros(len(scales))
        # computing RMS for each window
        for e, sc in enumerate(scales):
            fluct[e] = np.sqrt(np.mean(self.compute_rms(y, sc) ** 2))
        # fitting a line to rms data
        coeff = np.polyfit(np.log10(scales), np.log10(fluct), 1)
        normalized_dfa = 1 / (1 + np.exp(-coeff[0]))
        return normalized_dfa


class TimeSeriesStatistics(SampleProcessor):
    def process(self, sample_data: np.ndarray) -> Dict[str, float]:
        # removing nan's
        sample_data: np.ndarray = sample_data[~np.isnan(sample_data)]
        return {
            "min": sample_data.min(),
            "max": sample_data.max(),
            "mean": sample_data.mean(),
            "var": sample_data.var(),
            "skewness": skew(sample_data),
            "kurtosis": kurtosis(sample_data)
        }


class MPT(SampleProcessor):
    def process(self, sample_data: AudioSample) -> float:
        return len(sample_data.data) / sample_data.rate


class MaximumPhonationUntilVoiceBreak(SampleProcessor):
    @staticmethod
    def compute_NVB(snd):
        pitch = snd.to_pitch()
        pulses = parselmouth.praat.call([snd, pitch], "To PointProcess (cc)")
        voice_report_str = parselmouth.praat.call([snd, pitch, pulses],
                                                  "Voice report", 0.0, 0.0, 75,
                                                  600, 1.3, 1.6, 0.03, 0.45)
        for el in voice_report_str.split('\n'):
            if len(el.split(':')) > 1:
                if 'Number of voice breaks' in el:
                    return float(el.split(':')[1])

    @classmethod
    def compute_MPTVB(cls, snd):
        if cls.compute_NVB(snd) == 0:
            return snd.duration
        else:
            start_points = list(np.arange(0.30, snd.duration, 0.25))
            for start_point in start_points:
                snd_part = snd.extract_part(
                    from_time=start_point - 0.05, to_time=start_point + 0.5)
                if cls.compute_NVB(snd_part) > 0:
                    return start_point

    def process(self, sample_data: AudioSample) -> float:
        try:
            sound = parselmouth.Sound(sample_data.data, sample_data.rate)
            return self.compute_MPTVB(sound)

        except parselmouth.PraatError as e:
            print(f"Sample {sample_data.name}, ({len(sample_data.data):d} "
                  f"samples): error {str(e)})")

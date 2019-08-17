#!/usr/bin/env python3

import audioop
from collections import deque
import pyaudio

THRESHOLD_FACTOR = 3.5
FIRST_PEAK_FACTOR = 0.8
SECOND_PEAK_FACTOR = 0.5


def get_oss_audio_device(dev="/dev/audio"):
    """Get the ossaudiodev."""
    try:
        import ossaudiodev

        audio = ossaudiodev.open(dev, "r")
        audio.setparameters(ossaudiodev.AFMT_S16_LE, 1, 44100)
        return audio
    except Exception:
        raise RuntimeError("Failed to open OSS audio device.")


class OsxAudio:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = None

    def __enter__(self):
        # input_device_index – Index of Input Device to use. Unspecified (or
        # None) uses default device. Ignored if input is False.
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=44100,
            input=True,
            frames_per_buffer=10000,
        )
        return self.stream

    def __exit__(self, *args, **kwargs):
        if not self.stream:
            return
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()


def get_chunk(src, bias):
    data = audioop.bias(src.read(10000), 2, bias)
    return data, audioop.maxpp(data, 2)


def get_swipe(audio):
    print("READY")
    baselines = deque([2 ** 15] * 4)
    bias = 0
    old_data = b""
    while 1:
        data, power = get_chunk(audio, bias)

        baseline = sum(baselines) / len(baselines) * THRESHOLD_FACTOR
        print(power, baseline, power / (baseline or 1))

        chunks = []
        while power > baseline:
            print(power, baseline, power / (baseline or 1), "*")
            chunks.append(data)
            data, power = get_chunk(audio, bias)

        if len(chunks) > 1:
            data = old_data + b"".join(chunks) + data
            while audioop.maxpp(data[:3000], 2) < baseline / 2:
                data = data[1000:]
            while audioop.maxpp(data[-3000:], 2) < baseline / 2:
                data = data[:-1000]

            return audioop.bias(data, 2, -audioop.avg(data, 2))

        old_data = data

        bias = -audioop.avg(data, 2)

        baselines.popleft()
        baselines.append(power)


def get_samples(data, width=2):
    return list(audioop.getsample(data, width, i) for i in range(len(data) // width))


def get_peaks(data):
    peak_threshold = audioop.maxpp(data[:1000], 2) * FIRST_PEAK_FACTOR

    samples = get_samples(data)

    i = 0
    old_i = 0
    sign = 1
    while i < len(samples):
        peak = 0
        while samples[i] * sign > peak_threshold:
            peak = max(samples[i] * sign, peak)
            i += 1

        if peak:
            if old_i:
                yield i - old_i
            old_i = i
            sign *= -1
            peak_threshold = peak * SECOND_PEAK_FACTOR

        i += 1


def get_bits(peaks):
    peaks = list(peaks)

    # Discard first 5 peaks
    peaks = peaks[5:]

    # Clock next 4 peaks (should be zeros)
    clocks = deque([p / 2.0 for p in peaks[:4]])

    i = 0
    while i < len(peaks) - 2:
        peak = peaks[i]

        if peak > 1.5 * sum(clocks, 0.0) / len(clocks):
            yield 0
            i += 1
            clocks.append(peak / 2)
        else:
            yield 1
            i += 2
            clocks.append(peak)
        clocks.popleft()


def get_bytes(bits, width=5):
    bits = list(bits)

    # Discard leading 0s
    while bits[0] == 0:
        bits = bits[1:]

    while 1:
        byte, bits = bits[:width], bits[width:]
        if len(byte) < width or sum(byte) % 2 != 1:
            return
        yield byte


def bcd_chr(byte):
    return chr(int("".join(map(str, byte[-2::-1])), 2) + 48)


def get_bcd_chars(bytes):
    bytes = list(bytes)

    if bcd_chr(bytes[0]) != ";":
        # Try reversed
        bytes = [byte[::-1] for byte in reversed(bytes)]

    ibytes = iter(bytes)

    start = next(ibytes)
    if bcd_chr(start) != ";":
        raise DecodeError("No start sentinal")

    lrc = start
    try:
        while 1:
            byte = next(ibytes)
            char = bcd_chr(byte)

            for i in range(len(lrc) - 1):
                lrc[i] = (lrc[i] + byte[i]) % 2

            if char == "?":
                lrc[-1] = sum(lrc[:-1], 1) % 2
                real_lrc = next(ibytes)
                if real_lrc != lrc:
                    raise DecodeError("Bad LRC")
                return

            yield char

    except StopIteration:
        raise DecodeError("No end sentinal")


class DecodeError(Exception):
    pass


def get_data_from_linux():
    return get_swipe(get_oss_audio_device())


def get_data_from_osx():
    with OsxAudio() as audio:
        return get_swipe(audio)


def get_data_from_wav_file(filename="output.wav"):
    with open("capitalone.pcm", "rb") as f:
        return f.read()


if __name__ == "__main__":
    # data = get_data_from_linux()
    data = get_data_from_osx()
    # data = get_data_from_wav_file()
    peaks = list(get_peaks(data))
    bits = list(get_bits(peaks))
    bytes = list(get_bytes(bits))
    try:
        print("".join(get_bcd_chars(bytes)))
    except DecodeError as e:
        print(e)

import sys
import time
from pathlib import Path
import numpy as np

# Ensure root is in sys.path
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from faster_whisper.vad import get_vad_model
from utils.logger import log

class AudioPipelineBenchmark:
    """
    Performance benchmark utility for MXB Audio & VAD stages.
    Measures chunk evaluation latency, throughput (chunks/sec), and memory impact.
    """

    @classmethod
    def run_benchmark(cls, num_chunks: int = 500) -> dict:
        log.info(f"Benchmark: Starting Silero Neural VAD test ({num_chunks} chunks)...")
        vad = get_vad_model()

        # Generate realistic synthetic audio chunks (512 samples @ 16kHz)
        t = np.linspace(0, 0.032, 512, endpoint=False)
        tones = [
            (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32),
            np.zeros(512, dtype=np.float32),
            (0.3 * np.random.normal(0, 0.1, 512)).astype(np.float32)
        ]

        latencies = []
        t_start = time.perf_counter()

        for i in range(num_chunks):
            chunk = tones[i % 3]
            t0 = time.perf_counter()
            _ = vad(chunk)
            latencies.append((time.perf_counter() - t0) * 1000.0)  # ms

        total_time = time.perf_counter() - t_start
        avg_latency = float(np.mean(latencies))
        p95_latency = float(np.percentile(latencies, 95))
        throughput = float(num_chunks / total_time)

        results = {
            "num_chunks": num_chunks,
            "total_time_sec": round(total_time, 3),
            "avg_latency_ms": round(avg_latency, 3),
            "p95_latency_ms": round(p95_latency, 3),
            "throughput_chunks_per_sec": round(throughput, 1),
            "real_time_factor": round(32.0 / avg_latency, 1)  # Each chunk is 32ms of audio
        }

        log.info(f"Benchmark Results: Avg={avg_latency:.3f}ms, P95={p95_latency:.3f}ms, Throughput={throughput:.1f} chunk/s")
        return results

if __name__ == "__main__":
    res = AudioPipelineBenchmark.run_benchmark(300)
    print(res)

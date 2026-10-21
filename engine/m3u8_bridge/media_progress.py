from __future__ import annotations

import math
import time


class MediaProgress:
    """Parse cumulative FFmpeg -progress output without treating logs as percentages."""

    def __init__(self, update, activity):
        self.update = update
        self.activity = activity
        self.offset = 0
        self.fields = {}
        self.duration = 0.0
        self.seconds = 0.0
        self.started = time.monotonic()
        self.last_advance = self.started
        self.counters = {}

    def __call__(self):
        self.activity()

    def start(self, stage, duration=0):
        self.offset = 0
        self.fields = {}
        self.seconds = 0.0
        try:
            value = float(duration or 0)
            self.duration = value if math.isfinite(value) and value > 0 else 0.0
        except (ValueError, TypeError):
            self.duration = 0.0
        self.started = time.monotonic()
        self.last_advance = self.started
        self.counters = {}
        self.activity()
        self.update(processingStage=stage, processingProgress=None,
                    processingSeconds=0, processingDuration=self.duration,
                    processingSpeed='', processingStartedAt=int(time.time() * 1000),
                    speed='', speedBytesPerSecond=0)

    def feed(self, output):
        complete = output.rfind(b'\n') + 1
        if complete <= self.offset:
            return
        lines = output[self.offset:complete].decode('utf-8', 'replace').splitlines()
        self.offset = complete
        for line in lines:
            key, separator, value = line.partition('=')
            if not separator:
                continue
            self.fields[key] = value
            if key != 'progress':
                continue
            try:
                seconds = float(self.fields.get('out_time_us', '0')) / 1_000_000
                if math.isfinite(seconds):
                    self.seconds = max(self.seconds, seconds)
            except ValueError:
                pass
            percent = min(99.9, self.seconds * 100 / self.duration) if self.duration > 0 else None
            if value == 'end' and percent is not None:
                percent = 99.9  # Success still requires exit-code and output validation.
            speed = self.fields.get('speed', '')
            advanced = False
            for name in ('out_time_us', 'frame', 'total_size'):
                try:
                    counter = float(self.fields.get(name, '0'))
                    if math.isfinite(counter) and counter > self.counters.get(name, 0):
                        self.counters[name] = counter
                        advanced = True
                except ValueError:
                    pass
            if advanced:
                self.last_advance = time.monotonic()
                self.activity()
            self.update(processingProgress=percent, processingSeconds=self.seconds,
                        processingSpeed='' if speed == 'N/A' else speed)
            self.fields = {}

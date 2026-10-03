"""HTTPS-verified UTC, advanced with a monotonic clock between synchronizations."""
from email.utils import parsedate_to_datetime
from threading import Lock
import time
import urllib.request
import uuid


class UTCClock:
    def __init__(self):
        self._lock = Lock()
        self._anchor = None
        self._epoch = None
        self._last_attempt = None

    def now(self):
        with self._lock:
            mono = time.monotonic()
            needs_sync = self._anchor is None or mono - self._anchor > 300
            if needs_sync and (self._last_attempt is None or mono - self._last_attempt >= 30):
                self._last_attempt = mono
                samples = []
                for url in ('https://www.google.com/generate_204', 'https://www.cloudflare.com/cdn-cgi/trace'):
                    try:
                        start = time.monotonic()
                        request = urllib.request.Request(url + '?companion=' + uuid.uuid4().hex, headers={'Cache-Control': 'no-cache'})
                        with urllib.request.urlopen(request, timeout=4) as response:
                            dated = parsedate_to_datetime(response.headers['Date'])
                            if dated.tzinfo is None:
                                continue
                            stamp = dated.timestamp()
                            if int(response.headers.get('Age', '0')) > 0:
                                continue
                        end = time.monotonic()
                        if end - start <= 4:
                            samples.append((stamp, end))
                    except (OSError, ValueError, TypeError, KeyError):
                        continue
                if len(samples) == 2:
                    end = time.monotonic()
                    values = [stamp + end - at for stamp, at in samples]
                    if abs(values[0] - values[1]) <= 3:
                        # HTTP Date is only second-resolution. Stay behind its estimate so
                        # a bar cannot be treated as closed prematurely within clock uncertainty.
                        self._epoch, self._anchor = min(values) - 1, end
            if self._anchor is None or time.monotonic() - self._anchor > 900:
                raise RuntimeError('UTC_CLOCK_UNAVAILABLE: external UTC could not be verified')
            return self._epoch + time.monotonic() - self._anchor


clock = UTCClock()

"""Overpass API client: tries each mirror, backing off when they are busy."""

import json
import logging
import random
import time
from pathlib import Path

import requests
import urllib3

import config
from models import OverpassResponse

logger = logging.getLogger(__name__)


OVERPASS_USER_AGENT = "campspotter/1.0 (+https://github.com/jmwollny/campspotter)"


def get_overpass_mirrors() -> list[str]:
    # overpass.kumi.systems is not a default: it often hangs until the read timeout and
    # has returned incomplete results. Add it via OVERPASS_URLS if you want it.
    return list(config.get_settings().overpass_urls)


def sleep_with_jitter(min_seconds: float = 0.5, max_seconds: float = 1.5) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    logger.info(f"Waiting {delay:.2f}s before next Overpass mirror retry.")
    time.sleep(delay)


def write_overpass_debug_query(text: str | None) -> None:
    """Append Overpass queries/responses to a file for copy/paste debugging (DEBUG only)."""
    debug_filename = config.get_settings().overpass_query_debug_file
    debug_path = Path(__file__).resolve().parent / debug_filename
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with debug_path.open("a", encoding="utf-8") as debug_file:
        debug_file.write(f"\n--- {timestamp} ---\n")
        debug_file.write((text or "").strip())
        debug_file.write("\n")
    logger.debug(f"Appended Overpass query to {debug_path}")


class OverpassTooSlow(Exception):
    """A mirror kept the response going for longer than OVERPASS_TOTAL_TIMEOUT_S."""


def read_body(
    response: requests.Response, deadline: float, limit: int | None = None
) -> bytes:
    """
    Read a streamed response body, giving up at `deadline` (a time.perf_counter() value).

    The read timeout only limits the gap between packets, so a server that keeps a
    queued connection alive by sending a few bytes at a time can hold a request open for
    hours. read1() returns whatever has arrived, so the deadline is checked after every
    piece, however slowly the data trickles in. `limit` stops early (for error excerpts).
    """
    chunks: list[bytes] = []
    size = 0
    while limit is None or size < limit:
        if time.perf_counter() > deadline:
            raise OverpassTooSlow()
        chunk = response.raw.read1(64 * 1024, decode_content=True)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def call_overpass_with_retry(query: str) -> OverpassResponse | None:
    """
    POST a query to each Overpass mirror in turn; return the JSON payload or None.
    The public servers often answer 502/429 "at capacity" and ask clients to back off
    exponentially, so the mirror list is retried for OVERPASS_MAX_ROUNDS rounds with a
    doubling pause (OVERPASS_BACKOFF_S, 2x, 4x...) between rounds.
    """
    settings = config.get_settings()
    mirrors = get_overpass_mirrors()
    max_rounds = settings.overpass_max_rounds
    backoff_s = settings.overpass_backoff_s
    logger.info(
        f"Overpass request starting across {len(mirrors)} mirrors (query_size={len(query or '')} chars)."
    )
    if logger.isEnabledFor(logging.DEBUG):
        write_overpass_debug_query(query)

    for round_index in range(max_rounds):
        if round_index:
            delay = backoff_s * (2 ** (round_index - 1))
            logger.info(
                f"All Overpass mirrors failed; backing off {delay:.0f}s (round {round_index + 1}/{max_rounds})."
            )
            time.sleep(delay)
        payload, retryable = _try_overpass_mirrors(query, mirrors)
        if payload is not None or not retryable:
            return payload
    logger.error("Overpass request failed on all mirrors.")
    return None


def _try_overpass_mirrors(
    query: str, mirrors: list[str]
) -> tuple[OverpassResponse | None, bool]:
    """One pass over the mirrors -> (payload or None, whether retrying could help)."""
    settings = config.get_settings()
    retry_min_delay_s = settings.overpass_retry_min_delay_s
    retry_max_delay_s = settings.overpass_retry_max_delay_s
    # Short connect timeout so a dead mirror fails fast; generous read timeout for big
    # queries (the longest silence allowed); and a hard limit on the whole request.
    timeout = (settings.overpass_connect_timeout_s, settings.overpass_read_timeout_s)
    total_timeout_s = settings.overpass_total_timeout_s

    for index, url in enumerate(mirrors):
        mirror_start = time.perf_counter()
        deadline = mirror_start + total_timeout_s
        try:
            logger.info(f"Overpass request -> {url}")
            response = requests.post(
                url,
                data={"data": query},
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "User-Agent": OVERPASS_USER_AGENT,
                },
                timeout=timeout,
                stream=True,
            )
            try:
                ok = response.status_code == 200
                body = read_body(response, deadline, limit=None if ok else 2000)
            finally:
                response.close()
            elapsed = time.perf_counter() - mirror_start
            logger.info(
                f"Overpass response <- {url} status={response.status_code} elapsed={elapsed:.2f}s"
            )
            text = body.decode("utf-8", errors="replace")
            if ok:
                payload = json.loads(body)
                elements = (
                    payload.get("elements", []) if isinstance(payload, dict) else []
                )
                logger.info(f"Overpass success from {url}: elements={len(elements)}")
                if logger.isEnabledFor(logging.DEBUG):
                    write_overpass_debug_query(json.dumps(payload, indent=2))
                return payload, False
            if response.status_code == 400:
                # A syntax error will fail on every mirror, so stop here.
                logger.error(f"Overpass query syntax error (400): {text[:500]}")
                return None, False
            logger.warning(
                f"Overpass mirror returned status={response.status_code} at {url}. "
                f"Response excerpt: {text[:300]}"
            )
        except OverpassTooSlow:
            logger.warning(
                f"Overpass request to {url} took longer than {total_timeout_s:.0f}s "
                "(OVERPASS_TOTAL_TIMEOUT_S); giving up on it."
            )
        except requests.exceptions.Timeout as exc:
            logger.warning(f"Overpass request timeout for {url}: {exc}")
        except (
            requests.exceptions.RequestException,
            urllib3.exceptions.HTTPError,
        ) as exc:
            # urllib3 errors come from reading the streamed body (read timeouts, drops).
            logger.warning(f"Overpass request failed for {url}: {exc}")
        except ValueError as exc:
            logger.warning(f"Overpass response JSON decode failed for {url}: {exc}")
        if index < len(mirrors) - 1:
            sleep_with_jitter(retry_min_delay_s, retry_max_delay_s)
    return None, True

"""Overpass API client: tries each mirror, backing off when they are busy."""

import json
import logging
import random
import time
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)


OVERPASS_USER_AGENT = "campspotter/1.0 (+https://github.com/jmwollny/campspotter)"


def get_overpass_mirrors():
    # overpass.kumi.systems is not a default: it often hangs until the read timeout and
    # has returned incomplete results. Add it via OVERPASS_URLS if you want it.
    return list(config.get_settings().overpass_urls)


def sleep_with_jitter(min_seconds=0.5, max_seconds=1.5):
    delay = random.uniform(min_seconds, max_seconds)
    logger.info(f"Waiting {delay:.2f}s before next Overpass mirror retry.")
    time.sleep(delay)


def write_overpass_debug_query(text):
    """Append Overpass queries/responses to a file for copy/paste debugging (DEBUG only)."""
    debug_filename = config.get_settings().overpass_query_debug_file
    debug_path = Path(__file__).resolve().parent / debug_filename
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with debug_path.open("a", encoding="utf-8") as debug_file:
        debug_file.write(f"\n--- {timestamp} ---\n")
        debug_file.write((text or "").strip())
        debug_file.write("\n")
    logger.debug(f"Appended Overpass query to {debug_path}")


def call_overpass_with_retry(query):
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


def _try_overpass_mirrors(query, mirrors):
    """One pass over the mirrors -> (payload or None, whether retrying could help)."""
    settings = config.get_settings()
    retry_min_delay_s = settings.overpass_retry_min_delay_s
    retry_max_delay_s = settings.overpass_retry_max_delay_s
    # Short connect timeout so a dead mirror fails fast; generous read timeout for big queries.
    timeout = (settings.overpass_connect_timeout_s, settings.overpass_read_timeout_s)

    for index, url in enumerate(mirrors):
        mirror_start = time.perf_counter()
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
            )
            elapsed = time.perf_counter() - mirror_start
            logger.info(
                f"Overpass response <- {url} status={response.status_code} elapsed={elapsed:.2f}s"
            )
            if response.status_code == 200:
                payload = response.json()
                elements = (
                    payload.get("elements", []) if isinstance(payload, dict) else []
                )
                logger.info(f"Overpass success from {url}: elements={len(elements)}")
                if logger.isEnabledFor(logging.DEBUG):
                    write_overpass_debug_query(json.dumps(payload, indent=2))
                return payload, False
            if response.status_code == 400:
                # A syntax error will fail on every mirror, so stop here.
                logger.error(
                    f"Overpass query syntax error (400): {response.text[:500]}"
                )
                return None, False
            logger.warning(
                f"Overpass mirror returned status={response.status_code} at {url}. "
                f"Response excerpt: {(response.text or '')[:300]}"
            )
        except requests.exceptions.Timeout as exc:
            logger.warning(f"Overpass request timeout for {url}: {exc}")
        except requests.exceptions.RequestException as exc:
            logger.warning(f"Overpass request failed for {url}: {exc}")
        except ValueError as exc:
            logger.warning(f"Overpass response JSON decode failed for {url}: {exc}")
        if index < len(mirrors) - 1:
            sleep_with_jitter(retry_min_delay_s, retry_max_delay_s)
    return None, True

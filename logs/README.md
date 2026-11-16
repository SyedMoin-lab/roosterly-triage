# Run logs

Every run writes one JSON line per ticket to `logs/<UTC start time>-<run id>.jsonl`. A line holds the
ticket ID, the outcome (`posted`, `confirmed_by_read`, `already_handled`, `deferred`, ...), the action,
category, priority and confidence, the decider, and the duration. It never holds ticket text or
payment details.

Practice and drill runs stay local (`logs/*.jsonl` is git-ignored). The log of the final scored run is
committed on purpose.

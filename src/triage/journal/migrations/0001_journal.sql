CREATE TABLE epochs (
    epoch      integer PRIMARY KEY,
    reason     text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    run_id      uuid PRIMARY KEY,
    epoch       integer NOT NULL REFERENCES epochs (epoch),
    mode        text NOT NULL CHECK (mode IN ('live', 'dry_run')),
    decider     text NOT NULL,
    concurrency integer NOT NULL CHECK (concurrency > 0),
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    exit_code   integer,
    summary     jsonb
);

CREATE TABLE tickets (
    epoch         integer NOT NULL REFERENCES epochs (epoch),
    ticket_id     text NOT NULL,
    received_at   timestamptz NOT NULL,
    state         text NOT NULL DEFAULT 'new'
                  CHECK (state IN ('new', 'deciding', 'decided', 'posting', 'done', 'failed')),
    outcome       text,
    claimed_by    uuid REFERENCES runs (run_id),
    post_attempts integer NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (epoch, ticket_id)
);

CREATE INDEX tickets_by_state ON tickets (epoch, state, received_at);

CREATE TABLE decisions (
    epoch      integer NOT NULL,
    ticket_id  text NOT NULL,
    run_id     uuid NOT NULL REFERENCES runs (run_id),
    action     text NOT NULL CHECK (action IN ('reply', 'handoff', 'close')),
    body       jsonb NOT NULL,
    trace      jsonb NOT NULL DEFAULT '{}'::jsonb,
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (epoch, ticket_id),
    FOREIGN KEY (epoch, ticket_id) REFERENCES tickets (epoch, ticket_id)
);

CREATE TABLE control (
    name       text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

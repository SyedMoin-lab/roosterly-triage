CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE faq_vectors (
    faq_id      text NOT NULL,
    model       text NOT NULL,
    content_sha text NOT NULL,
    content     text NOT NULL,
    embedding   vector(768) NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (faq_id, model)
);

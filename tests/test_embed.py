"""Embedding tests with the real BAAI/bge-small-en-v1.5 (local cache). Reference = sentence-transformers (CLS pooling +
Normalize from the model card), computed in fp32."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from evret import embed as em

TEXTS = ["The cat sat on the mat.", "Vaccines do not cause autism, according to several large studies.",
         "A very short one", "Paris is the capital of France. " * 40, "x"]


@pytest.fixture(scope="module")
def enc():
    return em.Encoder(device="cuda" if torch.cuda.is_available() else "cpu")


@pytest.fixture(scope="module")
def reference():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(em.snapshot_dir(), device="cpu")
    return m


def test_passage_vectors_match_sentence_transformers(enc, reference):
    ref = reference.encode(TEXTS, normalize_embeddings=True, convert_to_numpy=True)
    got = enc.embed_passages(TEXTS)
    cos = (ref * got).sum(1)
    assert cos.min() > 0.999, cos                                     # fp16 vs fp32
    np.testing.assert_allclose(np.linalg.norm(got, axis=1), 1.0, atol=1e-4)
    assert got.shape == (5, 384)


def test_order_is_preserved_by_length_sorting(enc):
    a = enc.embed_passages(TEXTS)
    b = enc.embed_passages(TEXTS[::-1])[::-1]
    assert (a * b).sum(1).min() > 0.9995


def test_query_uses_instruction_and_fp32(reference):
    q = em.Encoder(device="cpu", dtype="fp32")
    query = "who discovered penicillin"
    got = q.embed_queries([query])
    ref_with = reference.encode([em.QUERY_INSTRUCTION + query], normalize_embeddings=True)
    ref_without = reference.encode([query], normalize_embeddings=True)
    assert float((got * ref_with).sum()) > 0.9999
    assert float((got * ref_without).sum()) < 0.999                  # the instruction really changes the vector
    assert q.model.dtype == torch.float32


def test_over_512_tokens_raises_instead_of_truncating(enc):
    with pytest.raises(ValueError):
        enc.encode_ids(["word " * 600])


def test_oom_halves_the_batch_and_retries(enc, monkeypatch):
    calls = {"n": 0}
    real = enc.embed_ids

    def flaky(ids):
        calls["n"] += 1
        if calls["n"] == 1:
            raise torch.cuda.OutOfMemoryError("simulated")
        return real(ids)
    monkeypatch.setattr(enc, "embed_ids", flaky)
    out = enc.embed_passages(TEXTS, token_budget=4000)
    assert out.shape == (5, 384) and calls["n"] >= 2 and np.isfinite(out).all()

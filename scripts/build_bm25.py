import sys
from evret import bm25
if __name__ == "__main__":
    corpus = sys.argv[1]
    for b in map(int, sys.argv[2:]):
        print(b, bm25.build_from_corpus(corpus, b, workers=3), flush=True)

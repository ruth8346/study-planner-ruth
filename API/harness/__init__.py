"""Hand-written harness for the Messages API. One file per responsibility; every
runtime action is printed with the name of the file that did it."""


def logger(filename: str):
    def log(msg: str) -> None:
        print(f"[{filename}] {msg}", flush=True)
    return log

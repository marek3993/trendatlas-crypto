from pathlib import Path

class WorkerLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b')
        import os
        if os.name=='posix':
            import fcntl
            fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        else:
            import msvcrt
            self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
            msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        return self
    def __exit__(self,*_):
        self.file.close()

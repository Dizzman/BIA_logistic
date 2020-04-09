import os
import sys
import time
import shutil

import importlib.util

sys.path.append('/home/aedeph/Work/gpn_logistic_2.0/rest/')
import restu

uf = restu.UPLOAD_FOLDER
of = restu.OUTPUT_FOLDER

print("Start executing main script")
for sec in range(5):
    time.sleep(1)
    print("Emulating processing for {} second".format(sec))

time.sleep(1)
print("Copying input to output")

for filename in os.listdir(uf):
    src = os.path.join(uf, filename)
    dst = os.path.join(of, filename)
    shutil.copyfile(src, dst)
    print("Moved {} to {}".format(src, dst))

print("Finished executing")

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ASAR = r"D:\DeepSeek Harness\resources\app.asar"
with open(ASAR, "rb") as f:
    d = f.read(4096)
print("hex[0:64]:")
h = d[:64].hex(" ")
for k in range(0, len(h), 48):
    print(" ", h[k:k+48])
i = d.find(b"{")
print("first '{' at offset:", i)
print("bytes around '{':", d[max(0,i-8):i+24])
offs, start = [], 0
while True:
    j = d.find(b"{", start)
    if j < 0: break
    offs.append(j); start = j + 1
print("all '{' offsets in first 4096 bytes:", offs[:20])

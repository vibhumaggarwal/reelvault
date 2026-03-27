# ReelVault format (v1)

Two layers: a **reel buffer** (header + payload) and a **frame codec** that draws that buffer into video frames. Every implementation (Python and the browser app) follows this document.

## Reel buffer

All integers are big-endian.

| Field | Bytes | Notes |
|---|---|---|
| magic | 4 | `RVLT` |
| version | 1 | `1` |
| flags | 1 | `0x01` deflate, `0x02` encrypted, `0x04` folder (payload is a zip) |
| name_len | 2 | |
| name | name_len | UTF-8, at most 1024 bytes |
| orig_size | 8 | size of the original file |
| payload_len | 8 | size of the payload as stored |
| crc32 | 4 | CRC-32 (IEEE) of the stored payload |
| salt | 16 | only if encrypted |
| nonce | 12 | only if encrypted |
| iterations | 4 | only if encrypted |
| payload | payload_len | |

### Processing order

Encoding: original bytes → (zip, if a folder) → raw deflate (if it makes the data smaller) → AES-256-GCM (if a password is set).

Decoding reverses this. Steps:

1. Check the CRC before decrypting or inflating.
2. If encrypted, decrypt. A failed GCM tag means a wrong password.
3. If deflated, inflate and check the result against `orig_size`.

### Encryption

- Key: PBKDF2-HMAC-SHA256(password as UTF-8, salt, iterations), 32 bytes.
- Cipher: AES-256-GCM with the 12-byte nonce, no additional data. The 16-byte tag is appended to the ciphertext, which is the default in both Python `cryptography` and WebCrypto.
- Writers use 600,000 iterations. Readers must honour the stored value.

### Compression

Raw deflate (RFC 1951, no zlib or gzip wrapper). In Python this is `zlib` with `wbits=-15`. In browsers it is `CompressionStream("deflate-raw")`.

## Frame codecs

The decoder tries both codecs on the first frame and uses the one that matches.

### Dense (lossless containers only)

The reel buffer is laid out byte by byte over the frame's pixels in the order `frame.tobytes()` gives in OpenCV: rows, then columns, then B, G, R. The last frame is zero-padded. Default frame size is 1280×720.

- **Detection:** the first 4 bytes of the first frame are `RVLT`.
- **Containers:** AVI with the PNG codec, or MKV with FFV1.

### Robust (any container)

Each frame is a 128×128 grid of cells, one bit per cell, read row by row. A 1 is white (255) and a 0 is black. Each cell is drawn as a `block`×`block` square, with a default block of 4, giving 512×512 frames.

| Cells | Field |
|---|---|
| 0–31 | frame index (MSB first) |
| 32–63 | total frame count |
| 64–79 | payload bits in this frame (≤ 16,304) |
| 80– | payload bits (the reel buffer as a bit stream, MSB of each byte first) |

Writers may repeat frames: both the Python writer and the browser emit each frame 3 times by default, because browsers decode by playing the video and can skip frames.

**Decoding:**

1. Convert each frame to grayscale and area-resize it to 128×128.
2. Group frames by index, and average each cell's brightness across all copies of that frame.
3. Threshold each cell at 127.
4. Read the frame count by majority vote, and report any missing indices.

**Detection:** frame index 0, a non-zero frame count, and payload bits that start with `RVLT`.

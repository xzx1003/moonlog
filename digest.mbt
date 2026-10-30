///|
// Incremental SHA-256 over exact input bytes (FIPS 180-4).
pub struct Sha256 {
  state : Array[UInt32]
  block : Array[Byte]
  schedule : Array[UInt32]
  mut length : UInt64
}

///|
pub fn Sha256::new() -> Sha256 {
  {
    state: [
      0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU, 0x510e527fU, 0x9b05688cU,
      0x1f83d9abU, 0x5be0cd19U,
    ],
    block: [],
    schedule: Array::make(64, 0U),
    length: 0UL,
  }
}

///|
fn rotr(x : UInt32, n : Int32) -> UInt32 {
  (x >> n) | (x << (32 - n))
}

///|
// Immutable round constants, shared across compression blocks.
let sha256_round_constants : Array[UInt32] = [
  0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
  0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
  0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
  0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
  0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
  0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
  0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
  0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
  0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
  0xc67178f2U,
]

///|
fn Sha256::compress(self : Sha256) -> Unit {
  let w = self.schedule
  for i in 0..<16 {
    let j = i * 4
    w[i] = (self.block[j].to_uint() << 24) |
      (self.block[j + 1].to_uint() << 16) |
      (self.block[j + 2].to_uint() << 8) |
      self.block[j + 3].to_uint()
  }
  for i in 16..<64 {
    let x = w[i - 15]
    let y = w[i - 2]
    w[i] = w[i - 16] +
      (rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3)) +
      w[i - 7] +
      (rotr(y, 17) ^ rotr(y, 19) ^ (y >> 10))
  }
  let mut a = self.state[0]
  let mut b = self.state[1]
  let mut c = self.state[2]
  let mut d = self.state[3]
  let mut e = self.state[4]
  let mut f = self.state[5]
  let mut g = self.state[6]
  let mut h = self.state[7]
  for i in 0..<64 {
    let t1 = h +
      (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) +
      ((e & f) ^ ((e ^ 0xffffffffU) & g)) +
      sha256_round_constants[i] +
      w[i]
    let t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) +
      ((a & b) ^ (a & c) ^ (b & c))
    h = g
    g = f
    f = e
    e = d + t1
    d = c
    c = b
    b = a
    a = t1 + t2
  }
  for i, value in [a, b, c, d, e, f, g, h] {
    self.state[i] += value
  }
  self.block.clear()
}

///|
pub fn Sha256::feed_byte(self : Sha256, byte : Byte) -> Unit {
  self.length += 1UL
  self.block.push(byte)
  if self.block.length() == 64 {
    self.compress()
  }
}

///|
// Consume a borrowed chunk synchronously; no view or source buffer is retained.
// Fill complete compression blocks without a per-byte function/callback.
pub fn Sha256::feed_bytes(self : Sha256, bytes : BytesView) -> Unit {
  self.length += bytes.length().to_uint64()
  let mut offset = 0
  while offset < bytes.length() {
    let count = (64 - self.block.length()).min(bytes.length() - offset)
    for i in 0..<count {
      self.block.push(bytes[offset + i])
    }
    offset += count
    if self.block.length() == 64 {
      self.compress()
    }
  }
}

///|
// Returns a digest without consuming the incremental state.
pub fn Sha256::hex(self : Sha256) -> String {
  let copy : Sha256 = {
    state: self.state.copy(),
    block: self.block.copy(),
    schedule: Array::make(64, 0U),
    length: self.length,
  }
  let bits = self.length * 8UL
  copy.feed_byte(0x80)
  while copy.block.length() != 56 {
    copy.feed_byte(0)
  }
  for i in 0..<8 {
    copy.feed_byte(((bits >> ((7 - i) * 8)).to_uint() & 255U).to_byte())
  }
  copy.state
  .map(fn(x) {
    let s = x.to_string(radix=16)
    "0".repeat(8 - s.length()) + s
  })
  .join("")
}

///|
test "sha256 matches the standard empty and abc vectors" {
  let empty = Sha256::new()
  assert_eq(
    empty.hex(),
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  )
  let abc = Sha256::new()
  for byte in [97, 98, 99] {
    abc.feed_byte(byte.to_byte())
  }
  assert_eq(
    abc.hex(),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  )
}

///|
test "sha256 multi-block and padding boundary vectors" {
  let long = Sha256::new()
  for byte in b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq" {
    long.feed_byte(byte)
  }
  assert_eq(
    long.hex(),
    "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
  )
  // NIST million-a vector also exercises incremental feeds across many blocks.
  let million = Sha256::new()
  for _ in 0..<1000000 {
    million.feed_byte(97)
  }
  assert_eq(
    million.hex(),
    "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
  )
  assert_eq(million.hex(), million.hex())
}

///|
test "sha256 padding length 55" {
  let digest = Sha256::new()
  for _ in 0..<55 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318",
  )
}

///|
test "sha256 padding length 56" {
  let digest = Sha256::new()
  for _ in 0..<56 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a",
  )
}

///|
test "sha256 padding length 63" {
  let digest = Sha256::new()
  for _ in 0..<63 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34",
  )
}

///|
test "sha256 padding length 64" {
  let digest = Sha256::new()
  for _ in 0..<64 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb",
  )
}

///|
test "sha256 padding length 65" {
  let digest = Sha256::new()
  for _ in 0..<65 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "635361c48bb9eab14198e76ea8ab7f1a41685d6ad62aa9146d301d4f17eb0ae0",
  )
}

///|
test "sha256 padding length 127" {
  let digest = Sha256::new()
  for _ in 0..<127 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "c57e9278af78fa3cab38667bef4ce29d783787a2f731d4e12200270f0c32320a",
  )
}

///|
test "sha256 padding length 128" {
  let digest = Sha256::new()
  for _ in 0..<128 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "6836cf13bac400e9105071cd6af47084dfacad4e5e302c94bfed24e013afb73e",
  )
}

///|
test "sha256 padding length 129" {
  let digest = Sha256::new()
  for _ in 0..<129 {
    digest.feed_byte(97)
  }
  assert_eq(
    digest.hex(),
    "c12cb024a2e5551cca0e08fce8f1c5e314555cc3fef6329ee994a3db752166ae",
  )
}

///|
// Two instances fed alternately must not share scheduling workspace state.
// Expected digests generated with Python hashlib, independent of this implementation.
test "sha256 interleaved instances keep independent state" {
  let left = Sha256::new()
  let right = Sha256::new()
  for i in 0..<300 {
    left.feed_byte(((i * 7 + 3) % 256).to_byte())
    if i < 200 {
      right.feed_byte(((i * 11 + 5) % 256).to_byte())
    }
  }
  assert_eq(
    left.hex(),
    "04773f8726c81cafcfa1a09a82664b98b00d2021031a1715bca1154f2dad3472",
  )
  assert_eq(
    right.hex(),
    "5db67eb0f85146ca32727c4d35e1c40be71b0f47d8f27f804d8cd45ebc602de3",
  )
}

///|
// hex() is a non-consuming snapshot: repeat calls stay stable and feeding can
// continue afterwards. Expected digests generated with Python hashlib.
test "sha256 hex snapshots allow continued feeding" {
  let digest = Sha256::new()
  for i in 0..<100 {
    digest.feed_byte(((i * 13 + 29) % 256).to_byte())
  }
  assert_eq(
    digest.hex(),
    "03af7e375195241ec501bb525e626b429d15b841d3dd0b4d94bd832a6369428c",
  )
  assert_eq(
    digest.hex(),
    "03af7e375195241ec501bb525e626b429d15b841d3dd0b4d94bd832a6369428c",
  )
  for i in 100..<127 {
    digest.feed_byte(((i * 13 + 29) % 256).to_byte())
  }
  assert_eq(
    digest.hex(),
    "67304575cc9c5e479761f86287ed66cd658c3d868d4980748a4c087eb65ffe1b",
  )
  digest.feed_byte(((127 * 13 + 29) % 256).to_byte())
  assert_eq(
    digest.hex(),
    "fa84435c0a8c5632f23f3b0ae68e4237e84b6d16a1f882d7914390a231eee9fb",
  )
  for i in 128..<192 {
    digest.feed_byte(((i * 13 + 29) % 256).to_byte())
  }
  assert_eq(
    digest.hex(),
    "fe9eb41a09f5cdabd1227c8a3dbe313d90eb5595aed0d591ac9707e5d2753a3b",
  )
}

///|
// Padding boundary lengths with distinct deterministic content; expected
// digests generated with Python hashlib, not with this implementation.
test "sha256 boundary lengths with independent expected values" {
  let cases : Array[(Int32, String)] = [
    (54, "c802146d5788fb540fbf29d8ff485730ad10f4f13b78961c032e78691b582647"),
    (57, "5b46e502092be01b1100193e089fdda95638c12e19a1d24f308eb2c3d3ae849d"),
    (119, "3d610547d68216dedf7435a4fb6260353911f6b3fd3f18805ddb8be285d726fe"),
    (192, "6e3a9b4ecba7af3a46e4f5c90fe02c99b5715144444b38049a42ac8313b30346"),
  ]
  for pair in cases {
    let digest = Sha256::new()
    for i in 0..<pair.0 {
      digest.feed_byte(((i * 31 + 7) % 256).to_byte())
    }
    assert_eq(digest.hex(), pair.1)
  }
}

///|
test "bulk SHA256 chunk boundaries match independent hashlib vectors" {
  let cases = [
    (0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    (1, "2b4c342f5433ebe591a1da77e013d1b72475562d48578dca8b84bac6651c3cb9"),
    (55, "24c40d6c311a5e2af2560e767218f0e14ac1465a1cd911e5eedb1349e1ec0dc8"),
    (56, "3d10707c921dcab8e6ec1ea5c62a1c04734df786f8be4e291d0748c6dfcce553"),
    (63, "41bbf050c0d3e7fb1cf766d490e221a18ae264bc087e1fff1308d663d647c467"),
    (64, "d02925fcb0ae75289059c5c04301667752b98849c9798c749afda9976068a6b0"),
    (65, "db932eef5d83309c6438edbe4af4e53ad1f4f799ffd57193d7a9ba6b94abc199"),
    (127, "74ec422f466fd7edf039357a1d8698bc61df379899231dfdfdc85dbe4839cb83"),
    (128, "26b73eca92233a2aeb3863632c2221c01d8e4fca598e2622d5938357d1cd35a5"),
    (129, "231286486fc0047c55a681990444108020b7a520a30bbf0609f308e7d6a81c1f"),
    (65535, "7cff66f1dd934093bf79a74ad253afa15ebe3a00a045ecd45931f8dab55257ed"),
    (65536, "b9facf50b7e1f662f64f2e377c0ba7fec88abe2d3234a362611ce925676c839c"),
    (65537, "bc390c19c2f3dab848f66887f1702a9ca35022a761203bf3f0eb28d404f1d62c"),
  ]
  for (size, expected) in cases {
    let data = Array::make(size, (0).to_byte())
    for i in 0..<size {
      data[i] = ((i * 17 + 9) % 256).to_byte()
    }
    let bytes = Bytes::from_array(data[:])
    for width in [1, 63, 64, 65, 4096, 65536] {
      let digest = Sha256::new()
      digest.feed_bytes(bytes[0:0])
      let mut offset = 0
      while offset < size {
        let end = (offset + width).min(size)
        digest.feed_bytes(bytes[offset:end])
        offset = end
      }
      assert_eq(digest.hex(), expected)
      assert_eq(digest.hex(), expected)
    }
    let mixed = Sha256::new()
    if size > 0 {
      mixed.feed_byte(bytes[0])
    }
    mixed.feed_bytes(bytes[if size > 0 { 1 } else { 0 }:size])
    assert_eq(mixed.hex(), expected)
  }
}

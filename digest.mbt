///|
// Incremental SHA-256 over exact input bytes (FIPS 180-4).
pub struct Sha256 {
  state : Array[UInt32]
  block : Array[Byte]
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
    length: 0UL,
  }
}

///|
fn rotr(x : UInt32, n : Int32) -> UInt32 {
  (x >> n) | (x << (32 - n))
}

///|
fn Sha256::compress(self : Sha256) -> Unit {
  let k = [
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U,
    0x923f82a4U, 0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U,
    0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U,
    0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
    0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU,
    0x5b9cca4fU, 0x682e6ff3U, 0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
  ]
  let w = Array::make(64, 0U)
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
      k[i] +
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
// Returns a digest without consuming the incremental state.
pub fn Sha256::hex(self : Sha256) -> String {
  let copy : Sha256 = {
    state: self.state.copy(),
    block: self.block.copy(),
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

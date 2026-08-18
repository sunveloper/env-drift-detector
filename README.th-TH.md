# env-drift-detector

> อ่านภาษาอื่น: [English](README.md)

จับ deploy ที่กำลังจะพังเพราะไม่มีใครอัปเดต `.env.example`

เมื่อมี push ที่เพิ่ม `os.getenv("STRIPE_WEBHOOK_SECRET")` แต่ไม่มีใครเพิ่ม
`STRIPE_WEBHOOK_SECRET` ลงใน `.env.example` เครื่องของคนเขียนจะไม่พังเลย —
เพราะค่านั้นอยู่ใน `.env` ของเขาอยู่แล้ว แต่มันจะพังสำหรับคนถัดไปที่ clone repo
และพังบน staging โดยมักโผล่มาเป็น `None` ห่างจากต้นเหตุจริงไปสามชั้น

เครื่องมือนี้สแกนไฟล์ที่ push ล่าสุดแตะ หาตัวแปร environment ทุกตัวที่โค้ดอ่าน
เทียบกับ template แล้วส่งผลเข้า Discord channel

## เหมาะกับใคร

**Backend developer** ที่ดูแล configuration ของ service และรวมถึงทุกคนที่ต้องรัน
service นั้น: คนใหม่ที่กำลังตั้งเครื่อง, tester ที่กางสภาพแวดล้อมใหม่,
คนที่รับเวร deploy

## รายงานอะไร

| ประเภท | ความหมาย | ผล |
| --- | --- | --- |
| **Committed credential** | ค่าใน repo มีรูปร่างเหมือน key จริง | exit code `1`, embed แดง, ค่าถูก redact |
| **Missing** | อ่านโดยไม่มี fallback และ template ไม่ได้ระบุไว้ | exit code `1`, embed แดง |
| **Undocumented but has a default** | อ่านแล้วไม่มีใน template แต่ทุกจุดที่อ่านมี fallback | exit code `0`, embed เหลือง |
| **Unused** | template ระบุไว้ แต่ไม่มีโค้ดไหนอ่าน | exit code `0`, embed เหลือง เฉพาะโหมด `--all` |
| **Ignored** | ชื่อที่ platform ให้มาเอง เช่น `PATH`, `CI`, `NODE_ENV` | ไม่รายงานเลย |

### ทำไม "มี default" ต้องแยกเป็นประเภทของตัวเอง

ค่าที่ไม่ใช่ secret มักเขียนแบบมี fallback:

```python
port = os.getenv("PORT", "8000")           # ไม่ตั้งค่าก็รันได้
level = os.getenv("LOG_LEVEL", "INFO")     # ไม่ตั้งค่าก็รันได้
key = os.getenv("STRIPE_SECRET_KEY")       # คืน None แล้วไปพังทีหลัง
```

มีแค่ตัวที่สามที่ทำให้ deploy พังได้ ดังนั้นมีแค่ตัวที่สามที่ทำให้ build fail
สองตัวแรกยังถูกรายงาน — คนที่ clone repo ควรรู้ว่ามีปุ่มนี้ให้ปรับ — แต่ไปอยู่ใน
ส่วนสีเหลืองที่ไม่บล็อก การยุบทั้งสามให้เป็น alert แดงอันเดียวคือวิธีสอนทีมให้
เลิกสนใจ alert

ตัวแปรที่ถูกอ่านทั้งสองแบบนับเป็น **missing**: ถ้ามีจุดใดจุดหนึ่งที่รับมือ
โดยไม่มีค่านั้นไม่ได้ service ก็ยังพังได้

รูปแบบ fallback ที่ตรวจจับได้:

| ภาษา | Optional | Required |
| --- | --- | --- |
| Python | `os.getenv("X", "d")`, `os.environ.get("X", "d")`, `environ.setdefault("X", "d")` | `os.getenv("X")`, `os.getenv("X", None)`, `os.environ["X"]` |
| JS / TS | `process.env.X ?? "d"`, `process.env.X \|\| "d"` | `process.env.X` |
| NestJS | `config.get("X", "d")`, `config.get("X") ?? "d"` | `config.get("X")`, `config.getOrThrow("X")` |
| Property files | `${X:d}`, `${X:-d}`, `${X-d}` | `${X}`, `${X:?error}` |
| Java / Kotlin | `System.getProperty("X", "d")`, `System.getenv("X") ?: "d"` | `System.getenv("X")` |

`os.environ["X"]` เป็น required เสมอ — มันโยน `KeyError` เมื่อไม่มีค่า จึงไม่มี
เส้นทาง fallback ส่วน `os.getenv("X", None)` บอกว่า "ไม่มี default" ชัดเท่ากับ
การละ argument ทิ้ง จึงถือเป็น required ด้วย

"Unused" ถูกปิดในโหมด push โดยเจตนา การสแกนเฉพาะไฟล์ที่เปลี่ยนหมายความว่า
ตัวแปรส่วนใหญ่ใน template ไม่อยู่ในชุดที่สแกนอย่างถูกต้องแล้ว การรายงานจึงเป็น
noise ล้วน ใช้ `--all` เมื่อต้องการคำตอบนั้น

### Committed credentials

ค่าสองประเภทในรายงานมาจากตัว repository เอง: fallback literal ใน source
และ placeholder ใน template

```python
os.getenv("PORT", "8000")          # รายงานพิมพ์ว่า: PORT (default `8000`)
```

การพิมพ์ค่าพวกนั้นปกติไม่มีปัญหา — ใครอ่าน repo ได้ก็อ่านค่านั้นได้
ข้อยกเว้นคือค่าที่ไม่ควร commit ตั้งแต่แรก:

```python
os.getenv("API_KEY", "sk_live_51H8sQ…")   # hardcode ไว้ใน source
```
```bash
# .env.example
STRIPE_SECRET_KEY=sk_live_51H8sQ…         # เอา key จริงมาแปะใน template
```

ทั้งสองเป็น bug ร้ายแรงอยู่แล้ว และการส่งค่าต่อเข้า Discord channel ทำให้แย่ลง:
chat history ถูกเก็บถาวรและมักมีสิทธิ์อ่านกว้างกว่า repository ดังนั้นค่าที่มี
รูปร่างเหมือน credential จะถูก **redact ใน output และรายงานเป็น finding**:

```
  COMMITTED CREDENTIAL (1) - rotate the value, then remove it from the repository:
    ! API_KEY  code default at src/billing/client.py:12
```

รายงานถือชื่อตัวแปร ที่มา และประเภท — ไม่มีค่า ไม่มีแม้แต่เศษของค่า
`tests/test_secrets.py` assert ว่าไม่มี slice ขนาด 8, 12 หรือ 16 ตัวอักษรของ
credential หลุดออกมาใน output

กรณีนี้ทำให้ build fail — credential ที่ commit แล้วควรหยุด pipeline และ
`--no-fail` เป็นทางออกถ้าการตรวจจับพลาด

#### อะไรนับว่ามีรูปร่างเหมือน credential

- **รูปแบบที่ผู้ออก key ประกาศเอง** — `sk_live_`, `sk_test_`, `ghp_`,
  `github_pat_`, `xoxb-`, `AKIA…`, `AIza…`, `SG.`, `glpat-`, `npm_`, `dop_v1_`,
  header ของ PEM private key, JWT
- **URL ที่มี password ฝังอยู่** — `postgres://user:realpassword@host/db`
- **blob เดาไม่ได้ที่ entropy สูง** — base64/hex ยาว 32 ตัวขึ้นไป และ Shannon
  entropy ตั้งแต่ 3.6 bit ต่อตัวอักษร

ค่าที่ประกาศตัวเองว่าเป็น stand-in จะไม่ถูก redact ไม่ว่าจะดูสุ่มแค่ไหน
เพราะการเห็น placeholder คือจุดประสงค์ของรายงาน ครอบคลุม
`sk_live_replace_with_your_key`, `postgres://admin:changeme@localhost/db` และ
`AKIAIOSFODNN7EXAMPLE` ซึ่งเป็น key ตัวอย่างในเอกสารของ AWS เอง

นี่คือ heuristic เรื่องรูปร่าง ไม่ใช่การตัดสินว่าอะไรลับ มันเอนไปทาง redact:
การ redact ค่าที่ไม่ลับทำให้คนอ่านเสีย `git show` หนึ่งครั้ง ในขณะที่ความผิดพลาด
ด้านตรงข้ามย้อนคืนไม่ได้

## การเปลี่ยนแปลงใน template

การตรวจ drift ตอบคำถาม "template ครบหรือยัง" มีอีกคำถามที่สำคัญไม่แพ้กัน:
"template เปลี่ยนแล้ว ฉันต้องทำอะไร" git เก็บ revision ก่อนหน้าของ
`.env.example` อยู่แล้ว เครื่องมือจึงอ่านด้วย `git show <base>:.env.example`
แล้วรายงานส่วนต่าง:

| เปลี่ยนอะไร | รายงานเป็น | ต้องแก้ที่เครื่องตัวเองไหม |
| --- | --- | --- |
| เพิ่มตัวแปร | `+ NAME (add it to your .env)` | ใช่ |
| ค่า placeholder เปลี่ยน | `~ NAME  "redis://…" -> "rediss://…"` | ใช่ — รูปแบบเปลี่ยน |
| ลบตัวแปร | `- NAME (safe to drop from your .env)` | ไม่ |

ในทางปฏิบัติ การเปลี่ยน placeholder คือตัวที่มีประโยชน์ที่สุด เมื่อ `REDIS_URL`
เปลี่ยนจาก `redis://` เป็น `rediss://` ไม่มีอะไรหายไปและไม่มี test ไหน fail —
แต่ค่าในเครื่องของทุกคนผิดแล้ว และแต่ละคนจะรู้ทีละคน สิ่งนี้เปลี่ยนมันให้เป็น
ข้อความ Discord เดียว

มีแค่ตัวแปรที่เพิ่มและ placeholder ที่เปลี่ยนซึ่งทำให้ embed เป็นสีเหลือง
การลบเป็นการเก็บกวาด ไม่ใช่งาน ทั้งหมดนี้ไม่กระทบ exit code ปิดการเทียบทั้งหมด
ด้วย `--no-template-history` หรือ `ENV_DRIFT_TEMPLATE_HISTORY=false`

quote ถูก normalize ก่อนเทียบ ดังนั้นการเปลี่ยน `A=x` เป็น `A="x"` ไม่ถูกรายงาน
การแก้เฉพาะ comment ก็ไม่ถูกรายงานเช่นกัน

### ทำไมไม่เคยอ่านค่าจริง

ส่วนขยายที่นึกถึงได้ทันทีคือเทียบ *ค่าจริง* แล้วเตือนเมื่อมีตัวไหนเปลี่ยน
เครื่องมือนี้เจตนาไม่ทำ และเหตุผลไม่ใช่เรื่องการเก็บ — ส่วนนั้นแก้ได้ —
แต่เป็นเรื่องการเข้าถึง

**การเก็บแก้ได้ และการ mask เป็นวิธีที่ผิดสำหรับปัญหานั้น** การตรวจว่า
"เปลี่ยนไหม" ไม่ต้องใช้ค่าเลย ใช้แค่ `HMAC-SHA256(salt, value)` ซึ่งปลอดภัยกว่า
การโชว์สามตัวหน้าและสามตัวท้ายอย่างชัดเจน เพราะการ mask คือการเก็บส่วนหนึ่งของ
secret จริง ถ้าปัญหามีแค่เรื่องการเก็บ การ hash ก็จบเรื่องแล้ว

**การเข้าถึงแก้ไม่ได้** ทั้ง hash และ mask ยังต้องอ่านค่าจริงก่อน ซึ่งหมายถึง
การ inject production configuration เข้า job ที่รันการตรวจ ทุกวันนี้เครื่องมือนี้
ไม่ต้องมีสิทธิ์เข้าถึง environment ใดเลย — นั่นคือสิ่งที่ทำให้มันปลอดภัยพอจะรัน
ทุก push และเป็นสิ่งที่ฟีเจอร์ mask จะยกทิ้งไปอย่างเงียบๆ CI job ที่ถือ secret
ทุกตัวของทุก environment เป็นปัญหาใหญ่กว่าตัวแปรที่ไม่มีเอกสารมาก

**และการ mask รั่วมากกว่าที่เห็น** ค่าที่มีโครงสร้างเปิดเผยรูปร่างของตัวเอง
ผ่านตัวอักษรต้นและท้าย:

```
postgres://admin:S3cr3t@db.internal:5432/app   ->  pos...app   (scheme, ชื่อ database)
sk_test_a1b2c3                                 ->  sk_...2c3   (เป็น test key ไม่ใช่ live)
DEBUG=true                                     ->  tru...rue   (กู้คืนได้ทั้งหมด)
```

หกตัวอักษรจาก token ยี่สิบตัวคือ 30% ของมัน และ Discord history ถูกเก็บถาวร
โดยมักมีคนอ่านได้มากกว่าคนที่เข้าถึง secret store ได้

**สุดท้าย "เปลี่ยนแล้ว" เป็นสัญญาณที่อ่อน** การ rotate secret เป็นเรื่องปกติและ
ควรทำ ดังนั้นการเตือนทุกครั้งที่ค่าเปลี่ยนคือ noise มันแยกไม่ได้ว่าเป็นการ
rotate ที่ถูกต้องหรือค่าที่ผิด

เวอร์ชันที่มีประโยชน์ของคำขอนี้ถูก implement แทน ในชื่อ
[`env-drift verify`](#env-drift-verify): มันเทียบค่าจริงกับ *placeholder* ที่
commit ไว้ ตอบคำถาม "ค่านี้ผิดไหม" ไม่ใช่ "ค่านี้เปลี่ยนไหม" และรันในที่ที่ค่า
อยู่อย่างถูกต้องแล้ว

template เป็นอีกกรณีโดยสิ้นเชิง: ค่าของมันเป็น placeholder โดยนิยาม และมันถูก
commit เข้า repository อยู่แล้ว การเทียบมันไม่ต้องมี cache และไม่ต้องมีสิทธิ์
เข้าถึงอะไร — git เป็นที่เก็บ

## `env-drift verify`

คำสั่งหลักถามว่า "template ครบหรือยัง" คำสั่งนี้ถามอีกครึ่ง: "template ครบแล้ว
แต่ environment *ของฉัน* ครบไหม" มันจับ `.env` ที่ copy มาจาก `.env.example`
แล้วไม่เคยแก้ ซึ่งเป็นวิธีที่พบบ่อยที่สุดที่ตัวแปรซึ่งมีเอกสารครบยังลงเอยผิดอยู่

```bash
env-drift verify                      # ตรวจ process environment
env-drift verify --env-file .env      # ตรวจไฟล์ที่ระบุแทน
env-drift verify --strict-placeholder # ตีธงทุกค่าที่ยังเท่ากับ template
env-drift verify --no-fail            # รายงานแต่ไม่ทำให้ fail
```

```
env-drift verify: checked 6 variable(s) from .env.example against the process environment

  NOT SET (2):
    - DATABASE_URL
    - REDIS_URL

  STILL THE TEMPLATE PLACEHOLDER (1):
    - STRIPE_SECRET_KEY
```

exit code `1` เมื่อมี finding, `2` ถ้าไม่พบ template หรือไฟล์ที่ระบุใน
`--env-file`

### อะไรนับเป็น finding

| สถานการณ์ | รายงาน |
| --- | --- |
| ค่าใน template ไม่ว่าง แต่ค่าจริงไม่มีหรือว่าง | `NOT SET` |
| ค่าจริงเท่ากับค่าใน template และค่านั้นดูเหมือน stand-in | `STILL THE TEMPLATE PLACEHOLDER` |
| ค่าจริงเท่ากับค่าใน template แต่ค่านั้นเป็น default จริง | ไม่รายงาน |
| ค่าใน template ว่าง | ไม่รายงาน — template บอกเองว่าไม่ต้องมีค่า |

template อาจถือ default จริงไว้ เช่น `PORT=3000`, `LOG_LEVEL=INFO`,
`ENV_EXAMPLE_PATH=.env.example` environment ที่เก็บค่าเหล่านั้นไว้ถือว่าถูกต้อง
การตีธงมันจะทำให้คำสั่งนี้ไร้ประโยชน์ในโปรเจ็กต์ที่เขียน template ดีพอดี
stand-in ถูกจำแนกจาก marker เช่น `replace`, `changeme`, `your-`, `placeholder`,
`<...>`, `@example.com` หรือตัวอักษรเดียวกันซ้ำหกตัวขึ้นไป ใช้
`--strict-placeholder` สำหรับโปรเจ็กต์ที่ template ไม่มี default จริงเลย

### ควรรันที่ไหน

คำสั่งนี้อ่านค่าจริง จึงควรรันในที่ที่ค่าอยู่แล้วอย่างถูกต้อง: เครื่องของ
developer หรือ deploy job ที่มี configuration inject เข้ามาแล้ว สองคุณสมบัติ
ทำให้ปลอดภัย:

- **รายงานถือชื่อตัวแปรและ verdict ไม่มีค่า ไม่มี hash ไม่มี prefix ไม่มีความยาว**
  `tests/test_verify.py` assert ข้อนี้ รวมถึงว่าไม่มีเศษของค่าขนาดสามตัวอักษร
  ปรากฏใน output
- **ไม่เก็บอะไรและไม่ส่งอะไรไปที่ไหน** `verify` ไม่มี option `--webhook` —
  โดยเจตนา เพื่อไม่ให้มีเส้นทางของโค้ดจากค่าจริงไปยัง external service
  มี test assert ว่า option นั้นไม่มีอยู่

นี่ก็เป็นเหตุผลที่ `verify` ไม่อยู่ใน push workflow: CI ไม่มีธุระอะไรกับการถือ
production configuration เพื่อทำ lint

## ภาษาที่สแกน

| Extractor | ไฟล์ | ตรวจจับด้วย | รูปแบบ |
| --- | --- | --- | --- |
| `python` | `.py`, `.pyi` | `ast` parse | `os.getenv("X")`, `os.environ["X"]`, `os.environ.get("X")`, `environ.setdefault("X", ...)` |
| `javascript` | `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs` | regex | `process.env.X`, `process.env["X"]`, `import.meta.env.X` |
| `nest-config` | เหมือน `javascript` | regex | `configService.get('X')`, `get<string>('X')`, `get('X', default)`, `getOrThrow('X')` |
| `property-placeholder` | `.yml`, `.yaml`, `.properties`, `.java`, `.kt` | regex | `${X}`, `${X:default}`, `${X:-default}`, `${X:?error}` |
| `java` | `.java`, `.kt` | regex | `System.getenv("X")`, `System.getProperty("X", "d")`, Kotlin `?:` fallback |

แยกตาม stack:

| Stack | ครอบคลุมด้วย |
| --- | --- |
| Python | `python` |
| Node.js, Express | `javascript` |
| Next.js | `javascript` — ส่ง `--template .env.local` ถ้าโปรเจ็กต์ใช้ไฟล์นั้นเป็น template |
| NestJS | `javascript` + `nest-config` ทั้งคู่รันบนไฟล์เดียวกัน |
| Java / Spring Boot | `property-placeholder` + `java` ทั้งคู่รันบนไฟล์เดียวกัน |
| docker-compose | `property-placeholder` — syntax `${VAR}` เดียวกัน ได้มาเป็นผลพลอยได้ |

Python ใช้ parser จริง ดังนั้นชื่อตัวแปรใน comment หรือ docstring ไม่ใช่
false positive ส่วน key ที่คำนวณขึ้น (`os.getenv(prefix + "NAME")`) ถูกข้าม —
ค่าของมันไม่มีทางรู้ได้โดยไม่รันโค้ด

`ConfigService` ยังรับใช้ configuration ที่ไม่เกี่ยวกับ environment เลย ดังนั้น
`nest-config` จึงมีข้อจำกัดสองข้อ ชื่อ receiver ต้องมีคำว่า "config"
(`configService`, `config`, `appConfig`) — `userService.get('X')` เป็นการค้นข้อมูล
และ key ต้องเป็น upper snake case เพราะ namespaced key ของ Nest
(`config.get('app.port')`) resolve กับ config object ไม่ใช่ environment
ส่วน `getOrThrow` ถือเป็น required เสมอ: มันประกาศตรงๆ ว่าการไม่มีค่าคือเรื่องร้าย

### Spring Boot

โค้ด Java แทบไม่อ่านตัวแปร environment โดยตรง มันอ่าน Spring property และไฟล์
property คือตัวที่ resolve ไปที่ environment:

```yaml
# application.yml
spring:
  datasource:
    url: ${DB_URL}            # ตัวแปร environment อยู่ที่นี่
```
```java
@Value("${spring.datasource.url}")   // โค้ด Java เห็นแค่ property key
private String url;
```

ดังนั้นการสแกน `.java` เพียงอย่างเดียวจะแทบไม่เจออะไร — ชื่อจริงอยู่ใน
`application.yml` และ `application.properties` `property-placeholder` อ่านไฟล์
เหล่านั้น และรองรับ `@Value("${DB_URL}")` ที่ annotation ระบุชื่อตัวแปร
environment โดยตรงด้วย ส่วน `java` ครอบคลุม `System.getenv` และ
`System.getProperty` ซึ่งข้ามชั้น property ไปเลย

กฎ upper snake case เดียวกันถูกใช้: `${DB_URL}` เป็นตัวแปร environment
ส่วน `${spring.datasource.url}` เป็น Spring property key ที่ resolve กับ
property source `System.getProperty("spring.profiles.active")` ถูกข้ามด้วย
เหตุผลเดียวกัน

`System.getProperty` ถูกรวมไว้แม้ว่ามันอ่าน JVM property ไม่ใช่ environment
เพราะในทางปฏิบัติค่ามาถึงในรูป `-Dkey=$KEY` จาก start script หรือ container
entrypoint — เป็น configuration surface เดียวกับที่ `.env` เขียนเอกสารไว้

รูปแบบ fallback ที่รู้จักทั้งหมด:

| เขียนแบบ | ความหมาย |
| --- | --- |
| `${DB_URL}` | Required |
| `${APP_PORT:8080}` | Optional, default `8080` (Spring) |
| `${APP_PORT:-8080}`, `${APP_PORT-8080}` | Optional (shell / docker-compose) |
| `${DB_URL:?must be set}` | Required — ข้อความคือ error message ไม่ใช่ fallback |

แยก default ที่ colon ตัวแรกเท่านั้น ดังนั้น default ที่เป็น JDBC URL อย่าง
`${DB_URL:jdbc:postgresql://localhost:5432/app}` ถูกอ่านอย่างถูกต้อง

`${{ ... }}` ของ GitHub Actions ไม่เคย match: ปีกกาไม่สามารถเป็นตัวเริ่มของชื่อ
upper snake case ได้

### การเพิ่ม stack

extractor แต่ละตัวเป็นหนึ่ง module ใต้ `src/env_drift/extractors/` ที่ expose
class ซึ่งเข้ากับ protocol `Extractor` ใน `extractors/base.py`:

```python
class Extractor(Protocol):
    name: str
    suffixes: frozenset[str]   # claimed file suffixes
    filenames: frozenset[str]  # claimed exact file names, e.g. application.yml

    def extract(self, source: str, relative_path: str) -> list[Usage]: ...
```

register instance นั้นใน `extractors/__init__.py` แล้วมันทำงานทันที ส่วน scanner,
การเทียบ และ reporter ไม่ต้องแก้อะไร — มันเห็นแค่ `list[Usage]` เท่านั้น
extractor มากกว่าหนึ่งตัว claim ไฟล์เดียวกันได้ ซึ่งเป็นวิธีที่ไฟล์ `.ts` ของ
Nest ถูกสแกนทั้ง `process.env` และ `ConfigService` โดยไม่มี extractor ตัวใด
ต้องรู้จักอีกตัว

## การติดตั้ง

ต้องมีก่อน: Python 3.10 หรือใหม่กว่า และ `git` อยู่ใน `PATH`

```bash
git clone <your-fork-url> env-drift-detector
cd env-drift-detector
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

ตั้งค่า:

```bash
cp .env.example .env
# แล้วแก้ .env แปะ Discord webhook URL ของคุณลงไป
```

รับ webhook URL จาก Discord: **Server Settings → Integrations → Webhooks →
New Webhook → Copy Webhook URL** ปฏิบัติกับมันเหมือน credential — ใครถือไว้ก็
โพสต์เข้า channel นั้นได้

## การใช้งาน

ตรวจ commit ล่าสุดของ repository ปัจจุบัน:

```bash
env-drift
```

ตรวจโดยไม่ส่งอะไรเข้า Discord:

```bash
env-drift --dry-run
```

ตัวอย่าง output เมื่อเจอ drift:

```
env-drift: scanned 3 file(s) against .env.example
  commit 9f2c41ab  feat(billing): add Stripe webhook handler

  MISSING from .env.example (2):
    - STRIPE_WEBHOOK_SECRET  read at src/billing/webhook.py:24
    - STRIPE_API_VERSION  read at src/billing/client.py:11, src/billing/client.py:58

  UNDOCUMENTED but has a default (1) - does not fail the build:
    - BILLING_TIMEOUT_SECONDS (default: "30")  read at src/billing/client.py:19

  TEMPLATE CHANGED since HEAD^:
    ~ REDIS_URL  placeholder changed: "redis://localhost" -> "rediss://localhost"
    Everyone should refresh their local .env.
```

exit code เป็น `1` เพราะสองรายการที่หายไป ดังนั้น CI หยุดที่นั่น ถ้า
`BILLING_TIMEOUT_SECONDS` เป็น finding เดียว exit code จะเป็น `0`

มีคำสั่งที่สอง `env-drift verify` อธิบายไว้[ด้านบน](#env-drift-verify)

### คำสั่งที่ใช้บ่อย

```bash
env-drift                                  # commit ล่าสุด แจ้ง Discord
env-drift --dry-run                        # commit ล่าสุด แสดงในเทอร์มินัลเท่านั้น
env-drift --all                            # ทั้ง tree รวมการตรวจ unused
env-drift --base origin/main               # ทุกอย่างตั้งแต่ main (ทั้ง PR)
env-drift --repo ../other-service          # repository อื่น
env-drift --ignore SENTRY_DSN,DEBUG_PORT   # ข้ามชื่อที่ระบุ
env-drift --no-fail                        # รายงานแต่ exit 0 เสมอ
env-drift --notify-on-success              # โพสต์ "all clear" สีเขียวด้วย
env-drift --no-template-history            # ข้ามการเทียบ template กับ revision ก่อนหน้า
```

### Exit codes

| Code | ความหมาย |
| --- | --- |
| `0` | ไม่มีอะไรหายไป หรือส่ง `--no-fail` มา ส่วน undocumented-with-a-default และ template entry ที่ค้างถูกรายงานแต่ไม่ทำให้ fail |
| `1` | มีตัวแปรที่ถูกอ่านโดยไม่มี fallback และไม่มีเอกสาร หรือเจอ committed credential |
| `2` | เครื่องมือรันไม่ได้: ไม่ใช่ git repo, ไม่พบ template, webhook ล้มเหลว |

ทั้งสองคำสั่งใช้ code ชุดเดียวกัน

## เอาไปใช้กับโปรเจ็กต์ของคุณ

repository นี้คือตัวเครื่องมือ service ของคุณไม่ต้องเอาโค้ดนี้ไปแปะไว้ —
มันติดตั้งเครื่องมือใน CI แล้วรันกับ working tree ของตัวเอง ไม่มีอะไรเพิ่มเข้า
dependency ของ service คุณ

### 1. เพิ่ม workflow หนึ่งไฟล์ใน service ของคุณ (5 นาที)

สร้าง `.github/workflows/env-drift.yml` ใน repository ที่ต้องการให้ตรวจ:

```yaml
name: env-drift

on: push

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # การ diff ต้องมี commit ก่อน push อยู่ในเครื่อง

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install env-drift
        run: pip install "git+https://github.com/<your-org>/env-drift-detector@main"

      - name: Check for env drift
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: env-drift --base "${{ github.event.before }}"
```

Python ใน runner เป็นเพียงวิธีที่เครื่องมือทำงาน service ที่เป็น Spring Boot
หรือ NestJS ไม่ต้องมี Python ของตัวเองเลย — `setup-python` เตรียมให้ใน job
และมันหายไปพร้อม runner

### 2. เพิ่ม secret (1 นาที)

**Settings → Secrets and variables → Actions → New repository secret** ชื่อ
`DISCORD_WEBHOOK_URL` ถ้าไม่มี เครื่องมือยังรันและยังทำให้ build fail เหมือนเดิม
เพียงแต่พิมพ์ลง job log แทนการโพสต์

### 3. บอกทีมเรื่อง `verify` (1 นาที)

เพิ่มสองบรรทัดใน README ของ service คุณเอง:

```bash
pip install "git+https://github.com/<your-org>/env-drift-detector@main"
env-drift verify --env-file .env    # หลัง copy .env.example เป็น .env
```

นี่คือสิ่งที่คนใหม่หรือ tester รัน แทนที่จะไปค้นพบว่าค่าหายไปจากการนั่งดู service
boot ไม่ขึ้น

ถ้าต้องการ ติดตั้ง pre-push hook เพื่อจับ drift ก่อนออกจากเครื่อง —
ดู[ด้านล่าง](#รันทุกครั้งที่-push)

### การ pin เวอร์ชัน

`@main` ตามตัว repository นี้ไปเรื่อยๆ สำหรับ service ที่ไม่ต้องการให้ตัวตรวจ
เปลี่ยนแบบไม่ทันตั้งตัว ให้ pin ที่ tag แทน:

```yaml
run: pip install "git+https://github.com/<your-org>/env-drift-detector@v1.0.0"
```

### เครื่องมือเดียว ใช้ได้หลาย repository

บรรทัด install เดียวกันใช้ได้กับทุก service ไม่มีอะไรในนี้ผูกกับ stack ใด
stack หนึ่ง: extractor registry เลือกตัวอ่านที่ถูกต้องตามไฟล์ ดังนั้น service
ที่เป็น Python, NestJS API และ Spring Boot ได้ workflow เดียวกันด้วยสองขั้น
เดียวกัน การเพิ่มเข้า repository ที่สี่คือการ copy-paste บวก secret หนึ่งตัว

## รันทุกครั้งที่ push

`.github/workflows/env-drift.yml` ใน repository *นี้* ตรวจ repository นี้เอง —
มันเป็นการ dogfood และเป็นตัวอย่างที่ใช้งานได้จริงให้ copy ไป เปิดใช้ที่นี่สองขั้น:

1. เพิ่ม repository secret ชื่อ `DISCORD_WEBHOOK_URL`
   (**Settings → Secrets and variables → Actions → New repository secret**)
2. push workflow ใช้ `github.event.before` เป็น diff base ดังนั้นการ push
   ห้า commit ถูกตรวจเป็นช่วงเดียว ไม่ใช่แค่ commit ปลายสุด

อยากจับก่อนที่มันจะออกจากเครื่อง? ติดตั้ง hook ในเครื่อง:

```bash
cp hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

## ค่าจริงอยู่ที่ไหน

**ไม่มีการ deploy ไฟล์ `.env` ไปที่ไหนเลย** ใน CI เครื่องมือนี้ต้องใช้ค่าจริง
เพียงตัวเดียว — Discord webhook URL — และอ่านจาก environment ซึ่งเป็นสิ่งที่
CI secret store inject ให้

| สิ่งของ | อยู่ที่ | commit ไหม |
| --- | --- | --- |
| `.env.example` | ใน repository | ใช่ — placeholder เท่านั้น |
| `.env` | เครื่อง developer เท่านั้น | ไม่ — อยู่ใน `.gitignore` |
| `DISCORD_WEBHOOK_URL` ตัวจริง | CI secret store | ไม่ใช่ไฟล์เลย |

`load_dotenv()` ใน `cli.py` เป็นความสะดวกสำหรับการรันในเครื่อง เมื่อไม่มี `.env`
มันไม่ทำอะไรและใช้ process environment แทน ซึ่งเป็นเส้นทางของ CI พอดี —
จึงไม่มี workflow step ไหนต้องสร้างไฟล์

ทำไมไม่เขียน `.env` ตอน CI รันไปเลย:

- เนื้อหาต้องมาจากที่ไหนที่หนึ่ง การ commit มันทำให้ credential เข้า git history
  อย่างถาวร และ history ล้างยาก
- GitHub mask ค่า secret ใน workflow log อัตโนมัติ ไฟล์ที่ build step `cat`
  ออกมาไม่มีใคร mask ให้

### CI platform อื่น

เครื่องมือนี้อ่านแค่ตัวแปร environment เท่านั้น จึงไม่ต้องแก้โค้ดอะไร:

| Platform | เก็บ webhook URL ที่ไหน |
| --- | --- |
| GitHub Actions | Settings → Secrets and variables → Actions |
| GitLab CI | Settings → CI/CD → Variables, ติ๊ก **Masked** |
| Jenkins | Credentials → Secret text แล้วใช้ `withCredentials` |
| Azure DevOps | Pipeline → Variables, ติ๊ก **Keep this value secret** |

### สแกน repository อื่น

`.env.example` ที่ถูกตรวจเป็นของ repository ที่กำลังสแกน ไม่ใช่ของเครื่องมือนี้
ไฟล์นั้นถูก commit ไว้ที่นั่นตามปกติอยู่แล้ว และเครื่องมืออ่านจาก working tree
ตรงๆ — ไม่มีอะไรต้องเตรียมเพิ่ม

ค่า *จริง* ของ repository นั้นก็ไม่ต้องมีเช่นกัน การเทียบเป็นการเทียบ **ชื่อ**
ตัวแปร ดังนั้นเครื่องมือไม่เคยอ่านค่า นี่คือเหตุผลที่มันรันใน CI ได้โดยไม่ต้องมี
สิทธิ์เข้าถึง production secret เลย

## การตั้งค่า

flag ชนะตัวแปร environment และตัวแปร environment ชนะค่า default

| ตัวแปร | Flag | Default | ใช้ทำอะไร |
| --- | --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | `--webhook` | ไม่มี | รายงานส่งไปที่ไหน ถ้าไม่มี output อยู่ในเทอร์มินัล |
| `ENV_EXAMPLE_PATH` | `--template` | `.env.example` | template ที่ใช้เทียบ |
| `ENV_DRIFT_IGNORE` | `--ignore` | ดูตารางด้านบน | ชื่อที่ข้าม คั่นด้วย comma แทนที่ list เดิมทั้งชุด ไม่ใช่เพิ่มต่อท้าย |
| `ENV_DRIFT_FAIL_ON_MISSING` | `--no-fail` | `true` | ตัวแปรที่หายไปทำให้ run fail หรือไม่ |
| `ENV_DRIFT_BASE_REF` | `--base` | `HEAD^` | จุดเริ่มของช่วงที่ diff |
| `ENV_DRIFT_TEMPLATE_HISTORY` | `--no-template-history` | `true` | เทียบ template กับ revision ก่อนหน้าหรือไม่ |

การส่ง `--webhook` ทาง command line ทำให้ credential เข้า shell history
ใช้ตัวแปร environment แทน

## Tech stack

- **Python 3.10+** — `ast` จาก standard library ทำหน้าที่ parse Python
- **httpx** — ส่ง Discord webhook
- **python-dotenv** — โหลด `.env` สำหรับการรันในเครื่อง
- **git** — เรียกผ่าน shell เพื่อเอารายชื่อไฟล์ที่เปลี่ยนและ metadata ของ commit
- **pytest** — ชุดทดสอบ
- **GitHub Actions** — ตัว trigger ตอน push

## ทำงานอย่างไร

```
git diff (changed files) -> registry picks extractors -> compare vs template -> console + Discord
```

แต่ละขั้นเป็น module แยกที่ไม่รู้จักขั้นถัดไป ซึ่งเป็นเหตุผลที่ scanner ทดสอบได้
ด้วย string ธรรมดา และการเทียบทดสอบได้ด้วย set ธรรมดา:

| Module | หน้าที่ |
| --- | --- |
| `git_source.py` | push แตะไฟล์ไหน และ metadata ของ commit |
| `scanner.py` | เปิดไฟล์ไหน แล้วส่งต่อให้ registry ไม่มีความรู้เรื่องภาษาเลย |
| `extractors/` | หนึ่ง module ต่อหนึ่ง stack คืนการอ่าน env var พร้อม `file:line` และว่าการอ่านนั้นมี fallback ไหม |
| `template.py` | ชื่อและค่า placeholder ที่ประกาศใน template |
| `verify.py` | `env-drift verify` — จำแนก environment จริง ส่งออกแค่ชื่อ |
| `secrets.py` | จำแนกค่าที่มีรูปร่างเหมือน credential เพื่อไม่ให้ถูกเผยแพร่ซ้ำ |
| `history.py` | template เปลี่ยนอะไรไปจาก base revision |
| `drift.py` | จำแนก: missing / undocumented-with-default / unused / ignored |
| `models.py` | `Usage` และ `DriftReport` — ค่าที่ส่งต่อระหว่างขั้น |
| `reporters/` | render ไปที่เทอร์มินัลหรือ Discord |
| `config.py` | ลำดับความสำคัญ: flag แล้ว environment แล้ว default |
| `cli.py` | ต่อทุกขั้นเข้าด้วยกัน และเป็นเจ้าของ exit code |

## การทดสอบ

```bash
pytest -q
```

integration test สร้าง git repository ชั่วคราวขึ้นสดๆ แล้วรัน CLI จริงกับมัน
รวมถึงกรณีที่พลาดง่าย: repo ที่ commit แรกไม่มี parent, push ที่ต้อง *ไม่*
รายงาน drift ที่มีอยู่ก่อนในไฟล์ที่มันไม่ได้แตะ และ push หลาย commit ที่ระบุ
base มาชัดเจน

## ข้อสมมติและข้อจำกัด

- ชื่อตัวแปรต้องเป็น string literal ชื่อที่สร้างขึ้นแบบ dynamic จะถูกข้าม
  ไม่ใช่เดา
- `.env.example` เป็นแหล่งความจริงว่าตัวแปร *ชื่อ* อะไร ไม่ใช่ว่าค่าควรเป็นอะไร
  ค่าในนั้นเป็น placeholder
- การตรวจ JS/TS และ Nest ใช้ regex ดังนั้น `process.env` ใน comment ของ JS
  ก็นับเป็นการใช้งาน นั่นเอนไปทางรายงานเกิน ซึ่งเป็นทิศทางที่ปลอดภัยกว่า
- Nest config key ที่เป็นตัวพิมพ์เล็กหรือมีจุดถือว่าไม่ใช่ environment และถูกข้าม
  โปรเจ็กต์ที่อ่าน `config.get('port')` จาก environment จริงๆ จะไม่ถูกครอบคลุม
- fallback ถูกจำแนกที่จุดอ่านเท่านั้น `value = os.getenv("X") or "default"`
  ในบรรทัดถัดไป หรือ default ที่ใส่ไว้ใน config class ยังถูกรายงานเป็น required
  อีกครั้ง รายงานเกินดีกว่าเงียบ
- การอ่านที่ห่อไว้ใน helper มองไม่เห็น ถ้าโปรเจ็กต์เรียก
  `env_flag("FEATURE_X", True)` และ helper เรียก `os.getenv(name)` ข้างใน
  scanner เห็น key ที่คำนวณขึ้นแล้วข้ามไป — ดังนั้น `FEATURE_X` จะโผล่เป็น
  *unused* ในโหมด `--all` แม้ว่ามันถูกอ่านจริง `config.py` ของเครื่องมือนี้เอง
  มีรูปแบบนั้น ซึ่งเป็นวิธีที่ค้นพบข้อจำกัดนี้ ทางแก้ชั่วคราว: ใส่ชื่อเหล่านั้น
  ลงใน `ENV_DRIFT_IGNORE` ติดตามไว้ใน `TODO.md`
- เครื่องมือแยก secret จากค่าตั้งค่าธรรมดาไม่ได้ — มันไม่เคยอ่านค่า จึงไม่มี
  ข้อมูลจะตัดสิน ทั้งสองต้องปรากฏใน template ซึ่งเป็นประเด็นสำคัญ: template
  ตอบคำถาม "ฉันต้องตั้งค่าอะไร" ไม่ใช่ "อะไรลับ"
- เทียบเฉพาะ template เท่านั้น เครื่องมือไม่อ่านค่าที่มีอยู่ใน environment จริง
  จึงบอกไม่ได้ว่า staging ขาดค่าที่มันเขียนเอกสารไว้ นี่เป็นเจตนา: มันไม่ต้องมี
  สิทธิ์เข้าถึง production เพื่อรัน

## ความปลอดภัย

- webhook URL ถูกอ่านจาก environment ไม่เคยถูกพิมพ์ และไม่เคยถูกใส่ใน error
  message
- host ปลายทางถูกตรวจกับโดเมนของ Discord เอง ดังนั้นตัวแปร environment ที่ถูก
  แก้ไขไม่สามารถเปลี่ยนทิศรายงานไปยัง endpoint ของผู้โจมตีได้
- รายงานมี *ชื่อ* ตัวแปรและตำแหน่ง `file:line` ค่าจะปรากฏเฉพาะเมื่อมันถูก commit
  เข้า repository อยู่แล้ว และไม่ปรากฏเลยเมื่อมันดูเหมือน credential — ดู
  [Committed credentials](#committed-credentials)
- `env-drift verify` อ่านค่าจริงและไม่ส่งค่าใดออกมาเลย แม้แต่เศษเดียว
  ทั้งสองคุณสมบัติถูก assert ด้วย test
- `.env` อยู่ใน `.gitignore` และ `.env.example` ถือแต่ placeholder

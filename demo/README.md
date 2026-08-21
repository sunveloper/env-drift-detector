## ประโยคเปิด (30 วินาที)

> `.env.example` คือ template ที่ commit ได้ บอกว่า service ต้องมี env var อะไรบ้าง
> `.env` ค่าจริงอยู่แต่ในเครื่องแต่ละคน อยู่ใน `.gitignore`
>
> ปัญหา: dev เพิ่ม `os.getenv("STRIPE_WEBHOOK_SECRET")` แต่ไม่เติมลง `.env.example`
> เครื่องเขาไม่พังเพราะค่านั้นอยู่ใน `.env` ของเขาแล้ว
> ที่พังคือคนถัดไปที่ clone repo, และ staging —
> โผล่มาเป็น `None` ห่างจากต้นเหตุจริงไปสามชั้น
>
> **เครื่องมือนี้สแกนไฟล์ที่ push แตะ ดึง env var ทุกตัวที่โค้ดอ่าน เทียบ template
> แล้วส่งเข้า Discord + fail build"**

จุดที่ต้องย้ำตั้งแต่ต้น: **เทียบแค่ชื่อ ไม่เคยอ่านค่า** เลยรันใน CI ได้โดยไม่ต้องมี
สิทธิ์เข้าถึง production secret

---

## เตรียมก่อน

```bash
cd C:\1\_Python\env-drift-detector
.venv\Scripts\activate         # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
env-drift --help
```

ต้องมี: Python 3.10+, git, Discord webhook URL (ถ้าจะโชว์ notify)

---

| ประเภท | เงื่อนไข | exit / สี |
|---|---|---|
| `COMMITTED CREDENTIAL` | ค่าใน repo รูปร่างเหมือน key จริง | `1` แดง (ค่าถูก redact) |
| `MISSING` | อ่านโดยไม่มี fallback + template ไม่ระบุ | `1` แดง |
| `UNDOCUMENTED but has a default` | ไม่มีใน template แต่ทุกจุดที่อ่านมี fallback | `0` เหลือง |
| `Unused` | template ระบุ แต่ไม่มีโค้ดอ่าน | `0` เหลือง — เฉพาะ `--all` |
| `Ignored` | ชื่อจาก platform: `PATH`, `CI`, `NODE_ENV` | ไม่รายงาน |

---

detection heuristic:

- **issuer-declared prefix** — `sk_live_`, `sk_test_`, `ghp_`, `github_pat_`,
  `xoxb-`, `AKIA…`, `AIza…`, `SG.`, `glpat-`, `npm_`, `dop_v1_`, PEM header, JWT
- **URL ที่ฝัง password** — `postgres://user:realpassword@host/db`
- **high-entropy blob** — base64/hex ยาว 32+ และ Shannon entropy ≥ 3.6 bit/char

self-declared stand-in ไม่ถูก redact ไม่ว่าจะดูสุ่มแค่ไหน — `sk_live_replace_with_your_key`,
`postgres://admin:changeme@localhost/db`, `AKIAIOSFODNN7EXAMPLE`
เพราะการเห็น placeholder คือจุดประสงค์ของรายงาน

เอนไปทาง redact: false positive เสีย `git show` หนึ่งครั้ง, false negative ย้อนคืนไม่ได้
เคสนี้ fail build — `--no-fail` เป็นทางออกถ้า detection พลาด

---

## นาที 0–2 · required vs optional

```python
port  = os.getenv("PORT", "8000")        # มี fallback → ไม่ตั้งก็รันได้
level = os.getenv("LOG_LEVEL", "INFO")   # มี fallback → ไม่ตั้งก็รันได้
key   = os.getenv("STRIPE_SECRET_KEY")   # ไม่มี fallback → คืน None แล้วพังทีหลัง
```

---

## นาที 2–5 · จับ drift

### รัน `env-drift` บน repo อื่น

`pip install -e` ลง console script ไว้ใน `.venv` ของ env-drift-detector
ตัว script ผูกกับ interpreter ของ venv นั้น จึงเรียกจาก cwd ไหนก็ได้ — **ขอแค่ venv ถูก activate**
ไม่ต้อง copy โค้ดเข้า target repo และ target repo ไม่ต้องเป็นโปรเจ็กต์ Python

**วิธี A — `--repo`** อยู่ใน env-drift-detector ตลอด ชี้ไปที่ target:

```bash
cd C:\1\_Python\env-drift-detector
.venv\Scripts\activate
env-drift --repo "C:\1\env-drift-demo-1787048002"  --dry-run
```

**วิธี B — `cd` เข้า target repo** venv ยัง activate อยู่ script ยังเรียกได้:

```bash
.venv\Scripts\activate                 # activate จาก env-drift-detector ก่อน
cd ../your-service
env-drift --dry-run
```

**ต่างกันที่ `.env` ไม่ใช่การสแกน** — `load_dotenv()` ใน `cli.py:165` โหลดจาก cwd
วิธี A จึงหยิบ `DISCORD_WEBHOOK_URL` จาก `.env` ของ env-drift-detector ให้เอง
วิธี B ไม่เจอไฟล์นั้น (`load_dotenv()` no-op) ต้องส่ง webhook เองถ้าจะยิง Discord:

```bash
DISCORD_WEBHOOK_URL="..." env-drift            # bash
$env:DISCORD_WEBHOOK_URL="..."; env-drift      # PowerShell
```

**วิธี C — ติดตั้งแบบ global ไม่ต้อง activate อะไร** เหมาะกับใช้ยาว:

```bash
# ทางที่ 1 — ติดตั้ง pipx ก่อน (ได้ isolated venv ต่อ tool, ถอนง่าย)
python -m pip install --user pipx
python -m pipx ensurepath          # ปิด terminal เปิดใหม่ ให้ PATH ติด
pipx install "git+https://github.com/sunveloper/env-drift-detector@main"

# ทางที่ 2 — pip --user ตรงๆ ไม่ต้องมี pipx
python -m pip install --user "git+https://github.com/sunveloper/env-drift-detector@main"
cd "C:\1\env-drift-demo-1787048002" && env-drift --dry-run
```

ทุกวิธีต้องการ **`.env.example` อยู่ใน root ของ target repo** — ไม่มีคือ exit `2`
path ที่เทียบ resolve เทียบกับ `--repo` ไม่ใช่ cwd (`cli.py:130-133`)
target repo ต้องเป็น git repo และมี commit ก่อนหน้าให้ diff (หรือส่ง `--base` เอง)

```bash
env-drift --repo ../your-service --template config/.env.sample   # template ไม่ได้อยู่ที่ root
env-drift --repo ../your-service --base origin/main --dry-run    # ทั้ง branch
env-drift verify --repo ../your-service --env-file ../your-service/.env
```

```bash
env-drift --dry-run            # commit ล่าสุด, ไม่ยิง webhook
```

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

```bash
env-drift --dry-run --all              # full tree + unused
env-drift --dry-run --base origin/main # ทั้ง PR ไม่ใช่แค่ HEAD
```

---

## นาที 5–7 · committed credential

```python
os.getenv("API_KEY", "sk_live_51H8sQ…")   # hardcode ใน source
```
```bash
STRIPE_SECRET_KEY=sk_live_51H8sQ…         # key จริงใน template
```

```
  COMMITTED CREDENTIAL (1) - rotate the value, then remove it from the repository:
    ! API_KEY  code default at src/billing/client.py:12
```

## นาที 7–9 · `env-drift verify`

คำสั่งหลักถาม "template ครบไหม" — `verify` ถามอีกครึ่ง: "environment **ของฉัน** ครบไหม"
จับเคสที่พบบ่อยสุด: `cp .env.example .env` แล้วไม่เคยแก้

```bash
env-drift verify                      # process environment
env-drift verify --env-file .env      # ไฟล์ที่ระบุ
env-drift verify --strict-placeholder # ตีธงทุกค่าที่ยังเท่ากับ template
```

```
env-drift verify: checked 6 variable(s) from .env.example against the process environment

  NOT SET (2):
    - DATABASE_URL
    - REDIS_URL

  STILL THE TEMPLATE PLACEHOLDER (1):
    - STRIPE_SECRET_KEY
```

| สถานการณ์ | รายงาน |
|---|---|
| template ไม่ว่าง แต่ค่าจริงไม่มี/ว่าง | `NOT SET` |
| ค่าจริง = ค่า template และค่านั้นดูเหมือน stand-in | `STILL THE TEMPLATE PLACEHOLDER` |
| ค่าจริง = ค่า template แต่เป็น default จริง (`PORT=3000`) | ไม่รายงาน |
| ค่าใน template ว่าง | ไม่รายงาน — template บอกเองว่าไม่ต้องมีค่า |

stand-in จำแนกจาก marker: `replace`, `changeme`, `your-`, `placeholder`, `<...>`,
`@example.com`, ตัวอักษรเดียวกันซ้ำ 6+ ตัว
ใช้ `--strict-placeholder` กับโปรเจ็กต์ที่ template ไม่มี default จริงเลย

ทำไมไม่อยู่ใน CI — คำสั่งนี้อ่านค่าจริง ควรรันที่ที่ค่าอยู่ถูกแล้ว: เครื่อง dev,
deploy job ที่ inject config มาแล้ว สองคุณสมบัติที่ทำให้ปลอดภัย:

- **output ถือชื่อ + verdict เท่านั้น** — ไม่มีค่า ไม่มี hash ไม่มี prefix ไม่มีความยาว
  `tests/test_verify.py` assert รวมถึงว่าไม่มีเศษขนาด 3 ตัวอักษรปรากฏ
- **ไม่มี option `--webhook`** โดยเจตนา — ไม่มี code path จากค่าจริงไป external service
  มี test assert ว่า option นั้นไม่มีอยู่

CI ไม่มีธุระถือ production configuration เพื่อทำ lint

---

## นาที 9–11 · coverage: extractor registry

```bash
env-drift --dry-run --all
```

| Extractor | ไฟล์ | วิธี | รูปแบบ |
|---|---|---|---|
| `python` | `.py`, `.pyi` | `ast` parse | `os.getenv`, `os.environ[...]`, `.get`, `setdefault` |
| `javascript` | `.js/.jsx/.ts/.tsx/.mjs/.cjs` | regex | `process.env.X`, `import.meta.env.X` |
| `nest-config` | เหมือน `javascript` | regex | `configService.get('X')`, `get<string>('X')`, `getOrThrow('X')` |
| `property-placeholder` | `.yml/.yaml/.properties/.java/.kt` | regex | `${X}`, `${X:default}`, `${X:-d}`, `${X:?err}` |
| `java` | `.java`, `.kt` | regex | `System.getenv`, `System.getProperty`, Kotlin `?:` |

ประเด็น: Python ใช้ `ast` (แม่น) ที่เหลือใช้ regex (เอนไปทางรายงานเกิน)
registry เลือก extractor จากนามสกุลไฟล์ ดังนั้น monorepo ที่มี Python service +
NestJS API + Spring Boot ใช้ workflow เดียวกัน

---

## นาที 11–13 · CI (สองขั้น)

`.github/workflows/env-drift.yml` ใน target repo:

```yaml
name: env-drift
on: push
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # diff ต้องมี commit ก่อน push อยู่ในเครื่อง
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "git+https://github.com/sunveloper/env-drift-detector@main"
      - env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: env-drift --base "${{ github.event.before }}"
```

secret: **Settings → Secrets and variables → Actions → New repository secret**
ชื่อ `DISCORD_WEBHOOK_URL` — pin เวอร์ชันโดยเปลี่ยน `@main` เป็น `@v1.0.0`

จับก่อนออกจากเครื่อง:

```bash
cp hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

---

รับคำถาม

---

## Q&A เตรียมไว้

**Q: ทำไมไม่ diff ค่าจริงว่าเปลี่ยนไหม?**
ไม่ใช่ปัญหา storage (แก้ได้) แต่เป็นปัญหา access — ต้องขอสิทธิ์อ่าน production config
ซึ่งแลกไม่คุ้ม ส่วนนั้น `verify` ทำในที่ที่ค่าอยู่ถูกแล้ว
template ต่างกัน: ค่ามันเป็น placeholder โดยนิยาม และ commit อยู่ใน repo แล้ว
git เป็นที่เก็บ ไม่ต้องมี cache ไม่ต้องมีสิทธิ์อะไร

**Q: false negative ที่รู้อยู่?**
- dynamic name (ไม่ใช่ string literal) ถูกข้าม ไม่เดา
- **helper wrapper มองไม่เห็น** — `env_flag("FEATURE_X", True)` ที่ข้างในเรียก
  `os.getenv(name)` scanner เห็น computed key แล้วข้าม ทำให้ `FEATURE_X` โผล่เป็น
  *unused* ใน `--all` แม้ถูกอ่านจริง `config.py` ของเครื่องมือเองมีรูปแบบนี้ —
  เป็นวิธีที่ค้นพบข้อจำกัดนี้ workaround: ใส่ชื่อใน `ENV_DRIFT_IGNORE` ติดตามใน `TODO.md`
- `os.getenv("X") or "default"` บรรทัดถัดไป และ default ใน config class ยังนับ required

**Q: false positive?**
JS/TS/Nest ใช้ regex ดังนั้น `process.env` ใน comment ก็นับเป็นการใช้งาน — เอนไป
ทางรายงานเกินโดยเจตนา / Nest key ที่เป็นตัวพิมพ์เล็กหรือมีจุดถือว่าไม่ใช่ environment
และถูกข้าม โปรเจ็กต์ที่อ่าน `config.get('port')` จาก environment จริงจะไม่ครอบคลุม

**Q: แยก secret จาก config ธรรมดาได้ไหม?**
ไม่ได้ — ไม่เคยอ่านค่า ไม่มีข้อมูลจะตัดสิน ทั้งสองต้องอยู่ใน template
เพราะ template ตอบ "ต้องตั้งค่าอะไร" ไม่ใช่ "อะไรลับ"

**Q (security): report leak ค่าได้ไหม?**
webhook URL อ่านจาก environment ไม่เคยถูกพิมพ์และไม่เคยอยู่ใน error message /
destination host ถูก validate กับโดเมนของ Discord ดังนั้น env var ที่ถูกแก้ไข
ไม่สามารถเปลี่ยนทิศรายงานไป endpoint ของผู้โจมตี / ค่าปรากฏเฉพาะเมื่อมันถูก commit
เข้า repo อยู่แล้ว และไม่ปรากฏเลยเมื่อดูเหมือน credential

---

## Plan B

- ไม่มี target repo พร้อม: `bash demo/demo.sh` — สร้าง demo repo บน GitHub อัตโนมัติ
  12 ขั้น มี pause กด Enter ครอบ Python + Spring Boot + NestJS + docker-compose
- คู่มือ onboarding ทีละขั้น: [demo/STEPS.md](STEPS.md)
- เหตุผลออกแบบทั้งหมด: [README.th-TH.md](../README.th-TH.md)

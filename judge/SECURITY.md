# Local OpenAI setup (Ama / judge)

The real API key must **never** be added to the GitHub repository, a pull request,
test fixture, screenshot, terminal command history, or ChatGPT conversation.

## Recommended: Codespaces secret

In GitHub: **Settings → Codespaces → Secrets**, create `OPENAI_API_KEY`
with repository access to `thantheinthwin/resolv-hackathon`. Restart the
Codespace. Then set `OPENAI_MODEL` in the Codespace environment (e.g. a
private `.env`) and never print the key.

## Alternative: local ignored .env

From the Codespace **repository root**:

```bash
umask 077
cp judge/.env.example .env
chmod 600 .env
# Edit .env using the Codespaces editor. Paste the key only there.
# Verify file stays ignored:
git check-ignore .env
stat -c '%a %n' .env
.venv/bin/python -m pip install -r judge/requirements.txt
```

Expected: `git check-ignore .env` prints `.env`, and `stat` prints `600 .env`.
Do not run `cat .env`, include keys in `git diff`, or use `git add -f`.
Rotate the key immediately if it appears in a commit or public log.

The judge loads only `OPENAI_API_KEY` and `OPENAI_MODEL` from the root `.env`
using `python-dotenv`. Exported Codespaces environment variables take
priority. The file must not be a symlink and must not grant group/other
permissions. No actual key is required for offline mocked tests.

## Privacy and usage

- Inspect and approve *all* sanitized frames and shop listing photos before
  any OpenAI request. Automatic Haar face detection does not grant approval.
- Review parcel labels and background for names, addresses and contact numbers.
  Never send raw parcel labels or original unboxing video files to the model.
- `store=False` disables normal response storage, but is **not a promise
  of zero provider retention**; use only consented demo data.
- Model outputs are untrusted observations, not final shop decisions.
- Limit model calls and only use `OPENAI_MODEL` approved for vision +
  structured outputs. Model availability depends on account entitlements.
- Cache responses only in untracked local data with restricted file access.

# Blocker register — 2026-09-02

| Severity | Gate | Evidence | Safe next action |
|---|---|---|---|
| Critical external | GitHub Actions billing for Codestra-SRL | Middleware PR #281 run 33606709169 failed before job assignment | Organization owner restores Actions billing; rerun exact head 5fa44e8d1c5f1cf62d6af0b984b86b9d1740fc96 |
| High | Backup authority not protected | Platform PR #182 | Pass exact-head CI/review and protected merge; install exact merge |
| High | Waves 4–5 incomplete | No deployment performed | Complete protected artifacts and controlled rollout after predecessor gates |

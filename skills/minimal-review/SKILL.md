---
name: minimal-review
description: Challenge unnecessary new code using frozen evidence and a specific alternative.
---
Review the current Code Ownership Review packet with fresh context. Look for additions whose behavior already exists; identify the existing implementation, callers, compatibility assumptions and a concrete validation step. The presence of a new class is a question to investigate. Cite only supplied atoms within the unit. Treat absent or insufficient context as unknown. Return the report format with pass_name minimal-review. State precisely what would have to be checked before removal. Never apply a patch or record a human decision.

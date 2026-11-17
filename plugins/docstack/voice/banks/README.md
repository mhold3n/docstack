# Multi-doc voice banks

Statistical mass (machine) plus curated archetype markdown (human/agent).

## Layout

| Path | Role |
|------|------|
| `archetypes/*.md` | Eight append-only exemplar docs |
| `schema/bank_entry.schema.json` | Frontmatter / entry contract |
| `../.cache/banks/<corpus_version>/` | Rebuilt count mass JSON |

## Banks

| Id | Mass | Archetype |
|----|------|-----------|
| `grammar` | Clause-cue rates | Sentence pairs |
| `word` | Unigrams | Typical content words |
| `word_combo` | Bigrams/trigrams | Collocations |
| `phrase` | 3–8 token spans | Formula phrases |
| `punctuation` | Punct rates | Policy excerpts |
| `phrasing` | Openers/transitions | Opening lines |
| `paragraph` | Length buckets | Short paragraphs |
| `technical_writing` | Units/tables/headers | Lab fragments |

## Commands

```bash
voicectl banks scaffold
voicectl banks rebuild
voicectl banks status
voicectl banks show word
voicectl banks verify
```

Mass rebuilds on `voicectl ensure` when banks are enabled. Archetype entries are appended by harvest agents; they must cite a real `references/active/` source.

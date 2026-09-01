# Reference Audit

The added references were checked against authoritative metadata before being
inserted into the bibliography. DOI records were queried through Crossref; the
ACL paper was checked against its ACL Anthology page; the arXiv record was
checked against the arXiv API for title, authors, and publication date.

| Key | Work | Verification source | Result |
| --- | --- | --- | --- |
| `yu2005devil` | Devil+ Language | Crossref DOI `10.1007/11535409_60` | Title, authors, 2005 venue, and pages match |
| `lattner2004llvm` | LLVM | Crossref DOI `10.1109/CGO.2004.1281665` | Title, authors, CGO 2004, and pages match |
| `barthe2009certificate` | Certificate translation | Crossref DOI `10.1145/1538917.1538919` | Title, authors, TOPLAS 2009, volume/pages match |
| `kang2018crellvm` | Crellvm | Crossref DOI `10.1145/3296979.3192377` | Title, author list, 2018 volume/pages match |
| `lopes2021alive2` | Alive2 | Crossref DOI `10.1145/3453483.3454030` | Title, authors, PLDI 2021, and pages match |
| `lachaux2020transcoder` | Unsupervised translation of programming languages | arXiv API `2006.03511` | Title, four authors, and 2020 publication date match |
| `wang2021codet5` | CodeT5 | ACL Anthology `2021.emnlp-main.685` and DOI `10.18653/v1/2021.emnlp-main.685` | Title, four authors, EMNLP 2021, pages, and DOI match |

The paper uses all 17 bibliography keys exactly once or more in the text; no
unverified placeholder entry was retained.

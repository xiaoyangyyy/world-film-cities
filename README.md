# 全球拍摄城市与剧情城市

Wikidata 上同时写了拍摄地（P915）和剧情地（P840）、而且两地不同的电影。范围不限欧洲。快照日期 2026-11-22。

一行表示：这部电影在 A 拍摄，剧情地点里有 B。它不表示 A 一定是在伪装成 B。多伦多拍成纽约比较接近替身；圣莫尼卡对洛杉矶、纽约对布鲁克林是相邻或从属。

只收录 Wikidata 已经填了这两个字段的电影。没有写入的片子不在表里。

## 这次快照

| 项目 | 数量 |
| --- | ---: |
| 电影 | 8174 |
| 拍摄地–剧情地配对 | 26974 |
| 两边都是城市的行 | 5006 |
| 两边都是城市的电影 | 2199 |
| 城市对 | 2934 |
| 拍摄地国家 | 149 |
| 剧情地国家 | 197 |

原始查询 27569 行。同一部电影、同一拍摄地、同一剧情地如果挂了多个国家，合并成一行，所以表里是 26974 对。

拍摄地电影数最多的是美国 3096、英国 876、加拿大 814、法国 691、意大利 457。中国 152。77 个国家只有 1 到 5 部。154 部电影的拍摄地没有国家。

## 文件

- `film_city_story.tsv`：全部配对
- `film_city_story_cities.tsv`：拍摄地和剧情地都被标成城市
- `city_pair_counts.tsv`：城市对和电影部数
- `summary.json`：计数和出现最多的 12 对
- `triples.csv`：Wikidata 原始三元组
- `place_types.csv`：地点类型
- `queries/`：当时的 SPARQL
- `assemble.py`：用三元组和地点类型生成三张表

## 列

`film_city_story.tsv` 的列是：

`film_qid`、`film_zh`、`film_en`、`year`、`shot_qid`、`shot_zh`、`shot_en`、`shot_country_qid`、`shot_country_zh`、`shot_country_en`、`shot_lat`、`shot_lon`、`shot_kind`、`story_qid`、`story_zh`、`story_en`、`story_country_qid`、`story_country_zh`、`story_country_en`、`story_lat`、`story_lon`、`story_kind`、`source`

`shot_kind` 和 `story_kind` 取 `城市`、`其他地点`、`虚构`。中文名来自 Wikidata 的中文标签，简体繁体都有。没有中文时，中文列会落成英文或 Q 号。

30 部电影没有上映年。450 个地点没有坐标。291 个地点没有国家。这些是 Wikidata 上的空项。

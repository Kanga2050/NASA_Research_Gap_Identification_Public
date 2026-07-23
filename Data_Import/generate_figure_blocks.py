"""The composite blocks the figure templates are built from.

Each block is saved as its own template (flagged as a block, so it lists under Blocks
and can be shared like any other), and returned here as {header, body} so a pipeline
can embed a frozen copy.

A definition is an ordinary graph with a boundary: __block_in__ emits one wire per
thing the block takes, __block_out__ accepts one wire per thing it hands back. The
ports and their types fall out of that wiring -- see block_ops.
"""
from App.Frontend.portal import block_ops, studio_ops

THEMES = [
    ("sc_bone", "bone", "bone density loss, osteoporosis, and skeletal deterioration in microgravity"),
    ("sc_muscle", "muscle", "skeletal muscle atrophy and musculoskeletal deconditioning during spaceflight"),
    ("sc_radiation", "radiation", "space radiation induced DNA damage, oxidative stress, and cancer risk"),
    ("sc_cardio", "cardiovascular", "cardiovascular deconditioning, fluid shifts, and orthostatic intolerance in astronauts"),
    ("sc_immune", "immune", "immune system dysregulation and altered immunity in spaceflight"),
    ("sc_vision", "neuro_ocular_SANS", "spaceflight associated neuro-ocular syndrome, vision impairment, and intracranial pressure"),
    ("sc_plant", "plant_crops", "plant growth, crop cultivation, and bioregenerative food production in space"),
    ("sc_microbe", "microbiome", "microbial behavior, microbiome changes, and infection risk in spacecraft"),
    ("sc_geneexp", "omics", "gene expression, transcriptomic, and epigenetic responses to microgravity"),
    ("sc_circadian", "circadian", "circadian rhythm disruption, sleep, and behavioral health in spaceflight"),
]
UNKNOWN_PROBE = ("unknown, poorly understood, remains to be determined, "
                 "further research is needed, an open question requiring future study")
FAVORABILITY = "spaceflight, microgravity, and space life sciences"
SPECTER2 = "allenai/specter2_base"


class Def:
    """A block definition under construction."""

    def __init__(self, name, inputs, description):
        self.name, self.description = name, description
        self.nodes, self.edges, self._i = [], [], 0
        self.inp = self.n("__block_in__", ports_out=max(1, len(inputs)),
                          block=name, labels=inputs, promoted=[])
        self.out = None

    def n(self, action, ins=(), csv="", column="", ports=None, ports_out=None, **fields):
        self._i += 1
        nid = str(self._i)
        node = {"id": nid, "action": action, "csv": csv, "column": column, "fields": fields}
        if ports is not None:
            node["ports"] = ports
        if ports_out is not None:
            node["ports_out"] = ports_out
        self.nodes.append(node)
        for port, src in enumerate(ins):
            if src is None:
                continue
            from_port = 0
            if isinstance(src, tuple):
                src, from_port = src
            self.edges.append({"from": src, "to": nid, "toPort": port, "fromPort": from_port})
        return nid

    def take(self, port):
        """Wire number `port` of what the block takes in."""
        return (self.inp, port)

    def give(self, *results, labels=()):
        """Declare what the block hands back."""
        self.out = self.n("__block_out__", ins=results, ports=max(1, len(results)),
                          labels=list(labels))

    def promote(self, node, param, name=None):
        self.nodes[0]["fields"]["promoted"].append(
            {"node": node, "param": param, "name": name or param})

    def save(self, user, blocks=None):
        """Save the definition as its own block template. ``blocks`` are the definitions
        this one is itself built from -- a block may be composed of blocks."""
        used = {n["action"][1:]: blocks[n["action"][1:]]
                for n in self.nodes
                if n["action"].startswith("@") and (blocks or {}).get(n["action"][1:])}
        saved = studio_ops.write_graph(user, self.name, self.nodes, self.edges,
                                       description=self.description, is_block=True,
                                       blocks=used or None)
        header = block_ops.derive_interface(self.nodes, self.edges, name=self.name)
        header["version"] = saved["version"]      # pin the version just written
        return {"header": header, "body": block_ops.definition_body(self.nodes, self.edges),
                "definition": {"nodes": self.nodes, "edges": self.edges}}


def build_all(user):
    blocks = {}

    # ---- Embed & Project -------------------------------------------------
    d = Def("Embed_And_Project", ["Text"],
            "SPECTER2 embeddings plus the UMAP projections every later step reads: "
            "5-D for clustering, 2-D for the maps.")
    emb = d.n("embed_text", ins=[d.take(0)], model_name=SPECTER2, output_column="text_embedding")
    d5 = d.n("reduce_dimensionality", ins=[emb], n_components=5, output_column="5d")
    d2 = d.n("reduce_dimensionality", ins=[emb], n_components=2, output_column="2d")
    d.give(emb, d5, d2, labels=["Embedding", "5-D coords", "2-D coords"])
    d.promote(emb, "model_name")
    blocks[d.name] = d.save(user)

    # ---- Topic Model -----------------------------------------------------
    d = Def("Topic_Model", ["Coordinates", "Text"],
            "HDBSCAN topic discovery over a coordinate column, with each topic named "
            "from its members' distinctive keywords.")
    topic = d.n("cluster", ins=[d.take(0)], min_cluster_size=32, min_samples=8,
                output_column="topic_id")
    label = d.n("label_topics", ins=[topic, d.take(1)], new_column_name="Topic_Label")
    d.give(topic, label, labels=["Topic id", "Topic label"])
    d.promote(topic, "min_cluster_size")
    d.promote(topic, "min_samples")
    blocks[d.name] = d.save(user)

    # ---- Relevance Score -------------------------------------------------
    d = Def("Relevance_Score", ["Text", "Embedding"],
            "Hybrid relevance: TF-IDF keyword scoring fused with SPECTER2 cosine "
            "similarity by reciprocal-rank fusion.")
    kw = d.n("keyword_score", ins=[d.take(0)], query=FAVORABILITY,
             output_column="keyword_favorability")
    sem = d.n("semantic_score", ins=[d.take(1)], query=FAVORABILITY,
              output_column="semantic_favorability")
    hyb = d.n("hybrid_score", ins=[kw, sem], output_column="hybrid_favorability")
    d.give(hyb, labels=["Relevance"])
    d.promote(kw, "query")
    d.promote(sem, "query", name="query")
    blocks[d.name] = d.save(user)

    # ---- Task Book Portfolio --------------------------------------------
    d = Def("Taskbook_Portfolio", [],
            "The NASA Task Book scrape: both collections parsed, stacked with a "
            "collection tag, and de-duplicated on task id into 6,353 unique awards.")
    search = d.n("parse_taskbook_pdfs", folders="Taskbook_Search_Pdfs",
                 csv_name="Taskbook_Search", source_label="NASA Task Book (Search)")
    biblio = d.n("parse_taskbook_pdfs", folders="Taskbook_Bibliography_Pdfs",
                 csv_name="Taskbook_Bibliography", source_label="NASA Task Book (Bibliography)")
    merged = d.n("combine_csvs", ins=[search, biblio], ports=2,
                 source_column="collection", output_csv="Taskbook_Combined")
    task_id = d.n("__column__", ins=[merged], column="task_id")
    portfolio = d.n("deduplicate", ins=[merged, task_id], output_csv="Taskbook_Portfolio")
    d.give(portfolio, labels=["Funded portfolio"])
    blocks[d.name] = d.save(user)

    # ---- Four Corpora ----------------------------------------------------
    d = Def("Four_Corpora", [],
            "All four windows in one table, tagged by corpus: the OpenAlex harvest, the "
            "OSDR and Decadal PDF corpora, and the funded Task Book portfolio. One "
            "Combine CSVs node stacks them, so every row keeps its own corpus name.")
    lit = d.n("openalex_scraper", topic="space biology", limit=101273, csv_name="Space_Biology")
    osd = d.n("chunk_pdfs", folders="OSDR_Pdfs", csv_name="OSDR", source_label="OSDR",
              chunk_words=250, overlap_words=40)
    dec = d.n("chunk_pdfs", folders="Decadal_Survey_Pdfs", csv_name="Decadal_Survey",
              source_label="Decadal Survey", chunk_words=250, overlap_words=40)
    tb = d.n("@Taskbook_Portfolio")
    combined = d.n("combine_csvs", ins=[lit, osd, dec, tb], ports=4,
                   source_column="dataset", output_csv="Combined_Corpus")
    d.give(combined, labels=["Combined corpus"])
    blocks[d.name] = d.save(user, blocks)

    # ---- Emphasis Probe (the repeated unit) ------------------------------
    # ONE risk theme's emphasis: score, average within each group, scale by x1000.
    # This four-node chain is the pattern the paper repeats ten times; it is a block so
    # it is drawn once and instantiated per theme, with the probe text (and the column
    # names it writes) exposed as arguments.
    d = Def("Emphasis_Probe", ["Table", "Group by", "Embedding"],
            "One risk theme's mean-centred emphasis: Semantic Score -> Group Aggregate -> "
            "Select Column -> Arithmetic (x1000). The repeated unit behind every "
            "cross-corpus and temporal emphasis figure; the query and the theme label are "
            "arguments, so one definition serves all ten themes.")
    probe = d.n("semantic_score", ins=[d.take(2)], query="", output_column="score")
    means = d.n("group_aggregate", ins=[d.take(0), d.take(1), probe], agg="mean",
                output_csv="Mean")
    value = d.n("__column__", ins=[means], column="score_mean")
    emph = d.n("arithmetic", ins=[means, value], operation="multiply", operand="1000",
               new_column_name="emphasis", output_csv="Emphasis")
    d.give(emph, labels=["Emphasis"])
    d.promote(probe, "query")
    d.promote(probe, "output_column", name="score_column")   # the per-passage score column
    d.promote(value, "column", name="mean_column")           # the aggregated column it picks
    d.promote(emph, "output_csv", name="theme")              # output table = theme label
    blocks[d.name] = d.save(user)

    # ---- Theme Emphasis --------------------------------------------------
    d = Def("Theme_Emphasis", ["Table", "Group by", "Embedding"],
            "The ten spaceflight-risk themes as one long (group, theme, emphasis) table: "
            "the Emphasis_Probe unit instantiated once per theme (each with its own probe "
            "and score column) and stacked by Combine CSVs, whose source tag -- the theme "
            "label each instance wrote -- becomes the theme column.")
    parts = []
    for key, tag, query in THEMES:
        parts.append(d.n("@Emphasis_Probe", ins=[d.take(0), d.take(1), d.take(2)],
                         query=query, score_column=key, mean_column=f"{key}_mean", theme=tag))
    long = d.n("combine_csvs", ins=parts, ports=len(parts), source_column="theme",
               output_csv="Theme_Emphasis_Long")
    d.give(long, labels=["Emphasis (long)"])
    blocks[d.name] = d.save(user, blocks)

    # ---- Theme Scores ----------------------------------------------------
    d = Def("Theme_Scores", ["Table", "Embedding"],
            "The same ten risk probes scored per passage, projected down to the "
            "per-paper profile table the co-occurrence analyses read.")
    for key, _tag, query in THEMES:
        d.n("semantic_score", ins=[d.take(1)], query=query, output_column=key)
    profiles = d.n("select_columns", ins=[d.take(0)],
                   columns="title,year," + ",".join(k for k, _, _ in THEMES),
                   output_csv="Theme_Profiles")
    d.give(profiles, labels=["Theme profiles"])
    blocks[d.name] = d.save(user)

    # ---- Acknowledged-Unknown Scores ------------------------------------
    d = Def("Unknown_Scores", ["Text", "Embedding"],
            "The acknowledged-unknown probe scored three ways -- TF-IDF, SPECTER2 and "
            "their reciprocal-rank fusion -- which is what the retrieval diagnostic of "
            "Figure 35 grades, and the lexical score the frontier is defined by.")
    kw = d.n("keyword_score", ins=[d.take(0)], query=UNKNOWN_PROBE, output_column="kw_unknown")
    sem = d.n("semantic_score", ins=[d.take(1)], query=UNKNOWN_PROBE, output_column="sem_unknown")
    hyb = d.n("hybrid_score", ins=[kw, sem], output_column="frontier_score")
    d.give(kw, hyb, labels=["Keyword (cue)", "Hybrid"])
    blocks[d.name] = d.save(user)

    # ---- Phrase Counts ---------------------------------------------------
    d = Def("Phrase_Counts", ["Table", "Text"],
            "Corpus-wide phrase counts: per-row n-gram frequencies summed into one "
            "key/sum table. Set the n-gram to 1 for terms, 2 for bigrams.")
    freq = d.n("word_frequency", ins=[d.take(1)], ngram=1, new_column_name="phrase_freq")
    counts = d.n("aggregate_dictionary", ins=[d.take(0), freq], output_csv="Phrase_Counts")
    d.give(counts, labels=["Counts"])
    d.promote(freq, "ngram")
    d.promote(counts, "output_csv", name="output_csv")
    blocks[d.name] = d.save(user)

    return blocks

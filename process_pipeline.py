import polars as pl

def add_action_num_reverse_chrono(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.col("ts")
          .rank(method="dense", descending=True)
          .over("session")
          .alias("action_num_reverse_chrono")
    )

def add_session_length(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.col("session")
          .count()
          .over("session")
          .alias("session_length")
    )
def get_session_lenghts(df):
    return df.group_by('session').agg([
        pl.col('session').count().alias('session_length')
    ])['session_length'].to_numpy()
    
def add_log_recency_score(df: pl.DataFrame) -> pl.DataFrame:
    expr = (
        pl.when(pl.col("session_length") == 1)
          .then(pl.lit(1.0))
          .otherwise(
            2 ** (
              0.1 +
              ((1 - 0.1) / (pl.col("session_length") - 1)) *
              (pl.col("session_length") - pl.col("action_num_reverse_chrono") - 1)
            ) - 1
          )
    )
    return df.with_columns(expr.alias("log_recency_score"))

def add_type_weighted_log_recency_score(df: pl.DataFrame) -> pl.DataFrame:
    type_weights = {0: 1, 1: 6, 2: 3}
    mapped = pl.col("type").replace_strict(type_weights)
    return df.with_columns(
        (pl.col("log_recency_score") / mapped)
          .alias("type_weighted_log_recency_score")
    )

pipeline = [
    add_action_num_reverse_chrono,
    add_session_length,
    add_log_recency_score,
    add_type_weighted_log_recency_score,
]

def apply(df: pl.DataFrame, pipeline) -> pl.DataFrame:
    for fn in pipeline:
        df = fn(df)
    return df

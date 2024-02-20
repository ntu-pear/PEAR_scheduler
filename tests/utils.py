import pandas as pd


def validateDF(result: pd.DataFrame, expected: pd.DataFrame):
    if (set(result.columns) != expected.columns):
        raise Exception(f"columns mismatch: \n expected {set(expected.columns)}\ngot {set(result.columns)}")
    
    if (result.shape != expected.shape):
        raise Exception(f"shape mismatch: expected {expected.shape} got {result.shape}")

    mismatched_columns = {}

    for col in expected.columns:
        mismatch = expected[col] != result[col]
        if mismatch.sum():
            mismatched_columns[col] = mismatch

    if mismatched_columns:
        error_msg = f"Data mismatch at columns {mismatched_columns.keys()}"

        for col, mismatch in mismatched_columns.items():
            error_df = pd.DataFrame({
                f"expected_{col}": expected[col][mismatch],
                f"result_{col}": result[col][mismatch]
            })
            error_msg += f"\n{error_df}"

        raise Exception(error_msg)

    return True

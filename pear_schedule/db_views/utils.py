from sqlalchemy import Select


def compile_query(query: Select) -> str:
    # literal binds might cause errors if datetime is ever used
    return query.statement.compile(compile_kwargs={"literal_binds": True})

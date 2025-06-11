from unittest.mock import MagicMock
from sqlalchemy.orm import Session


def get_db_session_mock():
    """
    Create a mock database session following the patient microservice pattern.
    Returns a mock that supports SQLAlchemy query chaining.
    """
    db_session_mock = MagicMock(spec=Session)
    
    # Create a mock query that supports method chaining
    mock_query = MagicMock()
    
    # Configure query methods to return chainable mock
    mock_query.filter.return_value = mock_query
    mock_query.filter_by.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.join.return_value = mock_query
    mock_query.group_by.return_value = mock_query
    mock_query.having.return_value = mock_query
    mock_query.distinct.return_value = mock_query
    
    # Configure terminal query methods
    mock_query.first.return_value = None
    mock_query.all.return_value = []
    mock_query.one.return_value = None
    mock_query.one_or_none.return_value = None
    mock_query.scalar.return_value = 0
    mock_query.count.return_value = 0
    
    # Configure aggregation functions
    mock_query.func = MagicMock()
    
    # Make session.query() return the chainable mock_query
    db_session_mock.query.return_value = mock_query
    
    # Configure session methods
    db_session_mock.add.return_value = None
    db_session_mock.add_all.return_value = None
    db_session_mock.commit.return_value = None
    db_session_mock.rollback.return_value = None
    db_session_mock.refresh.return_value = None
    db_session_mock.flush.return_value = None
    db_session_mock.execute.return_value = None
    db_session_mock.scalar.return_value = 0
    db_session_mock.close.return_value = None
    
    return db_session_mock

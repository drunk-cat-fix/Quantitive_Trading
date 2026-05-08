from libs.core.db import Base, engine
import libs.core.models  # noqa: F401


def init_db():
    Base.metadata.create_all(bind=engine)


if __name__ == '__main__':
    init_db()

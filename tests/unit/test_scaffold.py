import mio_cua


def test_package_importable():
    assert hasattr(mio_cua, "__version__")

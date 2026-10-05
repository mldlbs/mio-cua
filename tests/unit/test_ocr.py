from mio_cua.vision.ocr import _boxes_to_elements


def test_boxes_to_elements():
    boxes = [
        ([[0, 0], [50, 0], [50, 20], [0, 20]], "Save", 0.9),
        ([[100, 100], [200, 100], [200, 40], [100, 40]], "Open", 0.8),
    ]
    elements = _boxes_to_elements(boxes)
    assert len(elements) == 2
    assert elements[0].text == "Save"
    assert elements[0].bbox == (0, 0, 50, 20)
    assert elements[1].confidence == 0.8

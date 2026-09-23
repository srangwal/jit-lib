"""Copying Python data through JSON can change shared-object behavior.

Run: python3 04_json_changes_objects.py
This is an adapter limitation, not evidence of deliberate cheating.
"""

import json
from pprint import pprint


def make_pair():
    shared = [1, 2]
    return {"left": shared, "right": shared}


def main():
    direct = make_pair()
    copied = json.loads(json.dumps(make_pair()))

    print("Start with two names pointing to the same list [1, 2].")
    print("The initial values look identical after JSON copying:")
    pprint({"direct": direct, "after_json": copied})
    assert direct == copied

    print("\nDo the names still point to the SAME object?")
    print("Direct:", direct["left"] is direct["right"])
    print("After JSON:", copied["left"] is copied["right"])
    assert direct["left"] is direct["right"]
    assert copied["left"] is not copied["right"]

    direct["left"].append(3)
    copied["left"].append(3)
    print("\nAppend 3 through the left name, then read through the right name:")
    pprint({"direct_right": direct["right"], "after_json_right": copied["right"]})
    assert direct["right"] == [1, 2, 3]
    assert copied["right"] == [1, 2]

    circle = []
    circle.append(circle)
    print("\nPython also allows a list to contain itself:", circle[0] is circle)
    try:
        json.dumps(circle)
    except ValueError as error:
        print("JSON cannot encode that circular list:", error)
    else:
        raise AssertionError("Expected JSON to reject the circular list.")

    print("\nMatching initial values does not prove that an adapter preserves behavior.")
    print("Shared references, later mutations, and cycles need their own checks.")


if __name__ == "__main__":
    main()

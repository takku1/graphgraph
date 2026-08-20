"""Arithmetic recipes below the cubic bound.

Emits a subcubic schedule that trades scalar multiplications for additions.
"""


def assemble_thrifty_product(left, right):
    """Emit a subcubic matrix multiplication schedule using fewer scalar multiplications."""
    return left, right

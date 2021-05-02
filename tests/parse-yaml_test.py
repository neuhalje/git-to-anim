import unittest


class MyTestCase(unittest.TestCase):
    def test_something(self):
        myd = {"A": "aaaaa"}

        self.assertEqual( "aaaa", """{d["A"]}""".format(d=myd))


if __name__ == '__main__':
    unittest.main()

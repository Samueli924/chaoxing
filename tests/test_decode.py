import unittest

from api.decode import decode_course_list, decode_questions_info, _get_question_type


class DecodeTests(unittest.TestCase):
    def test_course_display_text_normalizes_non_breaking_spaces(self):
        html = """
        <div class="course" id="course-1" info="info" roleid="3">
          <input class="clazzId" value="20" />
          <input class="courseId" value="10" />
          <a href="/course?cpi=30&amp;ut=s"></a>
          <span class="course-name" title="Course&nbsp;Name"></span>
          <p class="margint10" title="Description&nbsp;Text"></p>
          <p class="color3" title="Teacher&nbsp;Name"></p>
        </div>
        """

        course = decode_course_list(html)[0]

        self.assertEqual(course["title"], "Course Name")
        self.assertEqual(course["desc"], "Description Text")
        self.assertEqual(course["teacher"], "Teacher Name")

    def test_question_decoder_returns_empty_result_when_form_is_missing(self):
        result = decode_questions_info("<html><body>login required</body></html>")

        self.assertEqual(result["questions"], [])
        self.assertEqual(result["answerwqbid"], "")

    def test_type_code_10_is_treated_as_completion(self):
        self.assertEqual(_get_question_type("10"), "completion")


if __name__ == "__main__":
    unittest.main()

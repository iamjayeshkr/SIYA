import pytest

from vani.browser import search


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_browser_search_exports_runtime_contract():
    assert hasattr(search.google_search, "ainvoke")
    assert callable(search.get_current_datetime)


def test_clean_query_strips_voice_fillers():
    assert search._clean_query("Google karo latest iPhone price") == "latest iPhone price"
    assert search._clean_query("best python tutorials google karo") == "best python tutorials"
    assert search._clean_query("  search for weather in Delhi  ") == "weather in Delhi"
    assert search._clean_query("cyber security article search karo on google") == "cyber security article"


def test_site_specific_search_extraction_and_urls():
    assert search._extract_site_search("udemy.com par ML course search karo") == (
        "udemy.com",
        "ML course",
    )
    assert search._site_search_url("udemy.com", "ML course") == (
        "https://www.udemy.com/courses/search/?q=ML+course"
    )
    assert search._extract_site_search("search two sum on leetcode.com") == (
        "leetcode.com",
        "two sum",
    )
    assert search._site_search_url("leetcode.com", "two sum") == (
        "https://leetcode.com/search/?q=two+sum"
    )
    assert search._site_search_url("google.com", "cyber security article") == (
        "https://www.google.com/search?q=cyber+security+article"
    )


@pytest.mark.anyio
async def test_google_search_falls_back_to_browser_without_api_keys(monkeypatch):
    opened = []

    monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
    monkeypatch.setattr(search, "_open_default", opened.append)

    result = await search.google_search.ainvoke({"query": "google karo machine learning"})

    assert result == "✅ Google search default browser mein khul gaya: machine learning"
    assert opened == ["https://www.google.com/search?q=machine+learning"]


@pytest.mark.anyio
async def test_google_search_routes_known_site_without_api_keys(monkeypatch):
    opened = []

    monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
    monkeypatch.setattr(search, "_open_default", opened.append)

    result = await search.google_search.ainvoke({"query": "udemy.com par ML course search karo"})

    assert result == "✅ 'ML course' ko udemy.com par search kar diya. Browser mein result khul gaya."
    assert opened == ["https://www.udemy.com/courses/search/?q=ML+course"]


@pytest.mark.anyio
async def test_google_search_opens_browser_when_api_request_fails(monkeypatch):
    opened = []

    class FailingRequests:
        class exceptions:
            RequestException = search.requests.exceptions.RequestException

        @staticmethod
        def get(*args, **kwargs):
            raise search.requests.exceptions.RequestException("offline")

    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "key")
    monkeypatch.setenv("SEARCH_ENGINE_ID", "cx")
    monkeypatch.setattr(search, "_open_default", opened.append)
    monkeypatch.setattr(search, "requests", FailingRequests)

    result = await search.google_search.ainvoke({"query": "machine learning"})

    assert result == "✅ Google search browser mein khul gaya: machine learning"
    assert opened == ["https://www.google.com/search?q=machine+learning"]


# LeetCode Problem: Two Sum
# Problem Statement:
# Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.
# You may assume that each input would have exactly one solution, and you may not use the same element twice.
# You can return the answer in any order.

def two_sum_solution(nums: list[int], target: int) -> list[int]:
    """
    Finds two numbers in the list that add up to the target.
    This implementation uses a hash map (dictionary) for optimal performance.

    Args:
        nums: A list of integers.
        target: The target sum.

    Returns:
        A list containing the indices of the two numbers.
    """
    # A dictionary to store numbers we've seen so far and their indices.
    # Key: number, Value: index
    num_map = {}

    for i, num in enumerate(nums):
        complement = target - num
        # Check if the complement (the number needed to reach the target) is already in our map
        if complement in num_map:
            # If yes, we've found our pair. Return their indices.
            return [num_map[complement], i]
        
        # If the complement is not found, add the current number and its index to the map
        # so it can be a complement for future numbers.
        num_map[num] = i
    
    # According to the problem statement, there will always be exactly one solution.
    # So, this line should theoretically not be reached.
    return []


def test_two_sum_problem_example_1():
    """Test case from LeetCode example: nums = [2, 7, 11, 15], target = 9"""
    nums = [2, 7, 11, 15]
    target = 9
    expected = [0, 1] # 2 + 7 = 9
    result = two_sum_solution(nums, target)
    # The order of indices doesn't matter, so sort both lists for consistent comparison
    assert sorted(result) == sorted(expected)


def test_two_sum_problem_example_2():
    """Test case from LeetCode example: nums = [3, 2, 4], target = 6"""
    nums = [3, 2, 4]
    target = 6
    expected = [1, 2] # 2 + 4 = 6
    result = two_sum_solution(nums, target)
    assert sorted(result) == sorted(expected)


def test_two_sum_problem_example_3():
    """Test case from LeetCode example: nums = [3, 3], target = 6"""
    nums = [3, 3]
    target = 6
    expected = [0, 1] # 3 + 3 = 6
    result = two_sum_solution(nums, target)
    assert sorted(result) == sorted(expected)


def test_two_sum_problem_negative_numbers():
    """Test case with negative numbers."""
    nums = [-1, -2, -3, -4, -5]
    target = -8
    expected = [2, 4] # -3 + -5 = -8
    result = two_sum_solution(nums, target)
    assert sorted(result) == sorted(expected)


def test_two_sum_problem_zero_target():
    """Test case with zero as target and mixed positive/negative numbers."""
    nums = [-1, 0, 1, 2]
    target = 0
    expected = [0, 2] # -1 + 1 = 0
    result = two_sum_solution(nums, target)
    assert sorted(result) == sorted(expected)


def test_two_sum_problem_large_numbers():
    """Test case with larger numbers."""
    nums = [100, 200, 300, 400]
    target = 600
    expected = [1, 3] # 200 + 400 = 600
    result = two_sum_solution(nums, target)
    assert sorted(result) == sorted(expected)

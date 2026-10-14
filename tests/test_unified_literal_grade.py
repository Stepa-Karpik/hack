from scripts.unified.literal_grade import normalized,distance

def test_literal_scoring_preserves_accents_case_and_ambiguous_digits():
    assert normalized('е\u0308  18.06.2029\n')=='ё 18.06.2029'
    assert distance(normalized('Александро́в'),normalized('Александров'))==1
    assert distance('О0','00')==1
    assert distance('А','а')==1
    assert distance('07.11.2027','07.01.2027')==1

def test_character_distance_counts_missing_and_invented_output():
    assert distance('abc','')==3
    assert distance('abc','abcd')==1
    assert distance('abc','axc')==1

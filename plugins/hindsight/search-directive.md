<purpose>Build the answer from consolidated observations. Any result set is a partial view of the bank; coverage of the question's named aspects is what can be checked, completeness cannot.</purpose>
<search-rules>
- Before done, every aspect the question names has its own search_observations call, phrased in that aspect's own vocabulary.
- After each search, search the same aspect once more using the terms the returned observations use, then mark it covered.
- Write from found observations only; state no preference an observation does not state.
</search-rules>

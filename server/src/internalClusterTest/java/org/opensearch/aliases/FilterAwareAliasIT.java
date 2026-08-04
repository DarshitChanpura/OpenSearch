/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.aliases;

import org.opensearch.action.admin.indices.alias.IndicesAliasesRequest.AliasActions;
import org.opensearch.action.search.SearchResponse;
import org.opensearch.action.support.WriteRequest.RefreshPolicy;
import org.opensearch.common.settings.Settings;
import org.opensearch.index.query.QueryBuilders;
import org.opensearch.test.OpenSearchIntegTestCase;

import static org.opensearch.test.hamcrest.OpenSearchAssertions.assertAcked;
import static org.opensearch.test.hamcrest.OpenSearchAssertions.assertHitCount;

/**
 * End-to-end verification of the filter-aware alias feature.
 * <p>
 * A term that appears ONLY in hidden (non-visible) documents inflates that term's
 * corpus-wide document frequency, which depresses its BM25 IDF. With today's
 * post-filtering ({@code enforcement: post_filter}, the default) the query scores
 * over every document in the shard before the alias filter is applied, so the
 * hidden {@code df} leaks into the score of a visible probe document — the
 * ExactOracle side-channel.
 * <p>
 * With {@code enforcement: pre_filter} the alias filter is pushed in front of
 * scoring, so the collection statistics only ever see visible documents. A
 * hidden-only term then scores identically to a term that exists nowhere — the
 * side-channel is closed. This test asserts exactly that difference, live.
 */
public class FilterAwareAliasIT extends OpenSearchIntegTestCase {

    private static final String INDEX = "patients";
    private static final String VISIBLE_DEPT = "cardiology";
    private static final String HIDDEN_DEPT = "oncology";
    private static final String SECRET_TERM = "infarction";   // planted only in hidden docs
    private static final String CONTROL_TERM = "zzqxkjpwvbm";  // exists in no document

    /** Build a corpus where SECRET_TERM appears only in hidden docs, plus a
     *  single visible probe doc that contains both the secret and control terms. */
    private void buildCorpus() throws Exception {
        assertAcked(
            prepareCreate(INDEX).setMapping("dept", "type=keyword", "content", "type=text")
                .setSettings(Settings.builder().put("index.number_of_shards", 1).put("index.number_of_replicas", 0))
        );

        // Many hidden docs carrying the secret term -> high corpus-wide df for it.
        for (int i = 0; i < 200; i++) {
            client().prepareIndex(INDEX)
                .setSource("dept", HIDDEN_DEPT, "content", "filler " + SECRET_TERM + " noise" + i)
                .get();
        }
        // A handful of visible docs (no secret term of their own).
        for (int i = 0; i < 20; i++) {
            client().prepareIndex(INDEX).setSource("dept", VISIBLE_DEPT, "content", "cardio note " + i).get();
        }
        // One visible probe doc containing BOTH the secret term and the control term.
        client().prepareIndex(INDEX)
            .setSource("dept", VISIBLE_DEPT, "content", "probe " + SECRET_TERM + " " + CONTROL_TERM)
            .setRefreshPolicy(RefreshPolicy.IMMEDIATE)
            .get();
        refresh(INDEX);
    }

    private void addAlias(String alias, String enforcement) {
        AliasActions add = AliasActions.add()
            .index(INDEX)
            .alias(alias)
            .filter(QueryBuilders.termQuery("dept", VISIBLE_DEPT));
        if (enforcement != null) {
            add.enforcement(enforcement);
        }
        assertAcked(client().admin().indices().prepareAliases().addAliasAction(add));
    }

    /** Score of the visible probe doc when the given view is queried for {@code term}. */
    private float probeScore(String view, String term) {
        SearchResponse resp = client().prepareSearch(view)
            .setQuery(QueryBuilders.matchQuery("content", term))
            .setSize(1)
            .get();
        if (resp.getHits().getTotalHits().value() == 0) {
            return 0f;
        }
        return resp.getHits().getHits()[0].getScore();
    }

    public void testPreFilterClosesScoringSideChannelWhilePostFilterLeaks() throws Exception {
        buildCorpus();
        addAlias("view_post", "post_filter"); // today's behavior (default)
        addAlias("view_pre", "pre_filter");   // filter-aware

        // Both views expose exactly the visible cardiology subset (21 docs).
        assertHitCount(client().prepareSearch("view_post").setSize(0).get(), 21);
        assertHitCount(client().prepareSearch("view_pre").setSize(0).get(), 21);

        // --- POST_FILTER: the secret term scores LOWER than the control term,
        //     because the hidden docs' df depresses its IDF. That gap is the leak.
        float postSecret = probeScore("view_post", SECRET_TERM);
        float postControl = probeScore("view_post", CONTROL_TERM);
        assertTrue("probe must be found for the secret term via post-filter alias", postSecret > 0f);
        assertTrue("probe must be found for the control term via post-filter alias", postControl > 0f);
        assertTrue(
            "post_filter leaks: secret score (" + postSecret + ") should sit below control (" + postControl + ")",
            postSecret < postControl
        );

        // --- PRE_FILTER: the secret term now scores the SAME as the control term,
        //     because scoring never saw the hidden docs. The gap collapses.
        float preSecret = probeScore("view_pre", SECRET_TERM);
        float preControl = probeScore("view_pre", CONTROL_TERM);
        assertTrue("probe must be found for the secret term via pre-filter alias", preSecret > 0f);
        assertTrue("probe must be found for the control term via pre-filter alias", preControl > 0f);
        assertEquals(
            "pre_filter closes the channel: secret and control scores must match",
            preControl,
            preSecret,
            0.0001f
        );

        // And concretely: the leak visible under post_filter is gone under pre_filter.
        float postGap = postControl - postSecret;
        float preGap = Math.abs(preControl - preSecret);
        assertTrue(
            "pre_filter score gap (" + preGap + ") must be far smaller than post_filter gap (" + postGap + ")",
            preGap < postGap
        );
    }
}

/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.search;

import org.apache.lucene.search.BooleanClause.Occur;
import org.apache.lucene.search.BooleanQuery;
import org.apache.lucene.search.ConstantScoreQuery;
import org.apache.lucene.search.Query;
import org.opensearch.action.search.SearchResponse;
import org.opensearch.action.support.WriteRequest.RefreshPolicy;
import org.opensearch.common.settings.Settings;
import org.opensearch.index.IndexModule;
import org.opensearch.index.query.ParsedQuery;
import org.opensearch.index.query.QueryBuilders;
import org.opensearch.index.query.QueryShardContext;
import org.opensearch.index.shard.SearchOperationListener;
import org.opensearch.plugins.Plugin;
import org.opensearch.search.internal.SearchContext;
import org.opensearch.test.OpenSearchIntegTestCase;

import java.util.Collection;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.opensearch.test.hamcrest.OpenSearchAssertions.assertAcked;

/**
 * Proves that an access-control plugin (modelled on document-level security) can obtain visible-subset BM25
 * scoring &mdash; the same property a {@code pre_filter} alias gets &mdash; through the
 * {@link SearchContext#filteredStatsFilter(Query)} seam, <b>without</b> an alias and <b>without</b> collapsing
 * scoring to a constant.
 * <p>
 * The plugin here mirrors exactly what the security plugin's {@code DlsFlsValveImpl.handleSearchContext} does at
 * search time: on {@code onPreQueryPhase} it (a) restricts which documents are returned by adding its restriction
 * query as a non-scoring {@code FILTER} clause, and (b) installs that same restriction as the filtered-stats
 * filter so BM25 collection/term statistics are computed over only the documents the caller may read. The
 * difference from the shipped {@code constant_score} DLS bridge is that scoring stays real BM25 (documents are
 * still ranked by relevance) &mdash; the seam removes the scoring side-channel without discarding ranking.
 * <p>
 * Two properties are asserted, both live:
 * <ul>
 *   <li><b>Leak-free:</b> a term that occurs only in restricted (non-visible) documents scores the same as a term
 *       that occurs nowhere &mdash; the restricted term's whole-shard {@code df} never enters a visible document's
 *       IDF.</li>
 *   <li><b>Still ranked:</b> the score the plugin produces equals the score of the same query against a physical
 *       index containing only the visible documents (real BM25 over the visible subset, not a flat constant).</li>
 * </ul>
 */
@OpenSearchIntegTestCase.ClusterScope(scope = OpenSearchIntegTestCase.Scope.TEST, numDataNodes = 1, numClientNodes = 0)
public class PluginFilteredStatsIT extends OpenSearchIntegTestCase {

    private static final String INDEX = "documents";
    private static final String VISIBLE_INDEX = "documents_visible_only";
    private static final String DEPT_FIELD = "dept";
    private static final String CONTENT_FIELD = "content";
    private static final String VISIBLE_DEPT = "cardiology";
    private static final String RESTRICTED_DEPT = "oncology";
    // Appears only in restricted (non-visible) docs -> inflates its whole-shard df.
    private static final String RESTRICTED_TERM = "infarction";
    // Appears in no document at all.
    private static final String ABSENT_TERM = "zzqxkjpwvbm";

    /**
     * A stand-in for the security plugin. When armed, on every query-phase it scopes the search to the
     * {@link #VISIBLE_DEPT} subset for the {@link #INDEX} index &mdash; both the returned documents and the BM25
     * statistics &mdash; using only released-shaped operations plus the new filtered-stats seam.
     */
    public static class VisibleSubsetPlugin extends Plugin {
        // Off by default so the physical ground-truth index we build is not itself filtered.
        static final AtomicBoolean ARMED = new AtomicBoolean(false);

        @Override
        public void onIndexModule(IndexModule indexModule) {
            indexModule.addSearchOperationListener(new SearchOperationListener() {
                @Override
                public void onPreQueryPhase(SearchContext searchContext) {
                    if (ARMED.get() == false) {
                        return;
                    }
                    String index = searchContext.indexShard().shardId().getIndex().getName();
                    if (INDEX.equals(index) == false) {
                        return;
                    }
                    QueryShardContext qsc = searchContext.getQueryShardContext();
                    Query restriction;
                    try {
                        restriction = qsc.toQuery(QueryBuilders.termQuery(DEPT_FIELD, VISIBLE_DEPT)).query();
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }

                    // (a) Restrict the returned documents: add the restriction as a non-scoring FILTER clause,
                    // exactly like DLS injects its restriction. Wrapping in ConstantScoreQuery keeps the filter
                    // itself from contributing to the score.
                    Query scoped = new BooleanQuery.Builder().add(searchContext.parsedQuery().query(), Occur.MUST)
                        .add(new ConstantScoreQuery(restriction), Occur.FILTER)
                        .build();
                    searchContext.parsedQuery(new ParsedQuery(scoped));

                    // (b) Scope BM25 statistics to the same visible subset via the seam. This is the one line the
                    // constant_score bridge cannot express: real scoring is preserved, but N/df come from the
                    // visible subset only.
                    searchContext.filteredStatsFilter(restriction);

                    searchContext.preProcess(true);
                }
            });
        }
    }

    @Override
    protected Collection<Class<? extends Plugin>> nodePlugins() {
        return List.of(VisibleSubsetPlugin.class);
    }

    @Override
    public void tearDown() throws Exception {
        VisibleSubsetPlugin.ARMED.set(false);
        super.tearDown();
    }

    private void buildCorpus() throws Exception {
        assertAcked(
            prepareCreate(INDEX).setMapping(DEPT_FIELD, "type=keyword", CONTENT_FIELD, "type=text")
                .setSettings(Settings.builder().put("index.number_of_shards", 1).put("index.number_of_replicas", 0))
        );
        // Many restricted docs carrying the restricted term -> raises its whole-shard df.
        for (int i = 0; i < 200; i++) {
            client().prepareIndex(INDEX)
                .setSource(DEPT_FIELD, RESTRICTED_DEPT, CONTENT_FIELD, "filler " + RESTRICTED_TERM + " n" + i)
                .get();
        }
        // Visible docs without the restricted term of their own.
        for (int i = 0; i < 20; i++) {
            client().prepareIndex(INDEX).setSource(DEPT_FIELD, VISIBLE_DEPT, CONTENT_FIELD, "cardio note " + i).get();
        }
        // One visible sample doc containing BOTH the restricted term and the absent term.
        client().prepareIndex(INDEX)
            .setSource(DEPT_FIELD, VISIBLE_DEPT, CONTENT_FIELD, "sample " + RESTRICTED_TERM + " " + ABSENT_TERM)
            .setRefreshPolicy(RefreshPolicy.IMMEDIATE)
            .get();
        refresh(INDEX);
    }

    /** Build the physical ground-truth: an index holding only the visible docs (plugin left disarmed). */
    private void buildVisibleOnlyIndex() throws Exception {
        assertAcked(
            prepareCreate(VISIBLE_INDEX).setMapping(DEPT_FIELD, "type=keyword", CONTENT_FIELD, "type=text")
                .setSettings(Settings.builder().put("index.number_of_shards", 1).put("index.number_of_replicas", 0))
        );
        SearchResponse visible = client().prepareSearch(INDEX)
            .setQuery(QueryBuilders.termQuery(DEPT_FIELD, VISIBLE_DEPT))
            .setSize(100)
            .get();
        for (org.opensearch.search.SearchHit hit : visible.getHits().getHits()) {
            client().prepareIndex(VISIBLE_INDEX).setSource(hit.getSourceAsMap()).get();
        }
        refresh(VISIBLE_INDEX);
    }

    private float sampleScore(String index, String term) {
        SearchResponse resp = client().prepareSearch(index).setQuery(QueryBuilders.matchQuery(CONTENT_FIELD, term)).setSize(1).get();
        if (resp.getHits().getTotalHits().value() == 0) {
            return 0f;
        }
        return resp.getHits().getHits()[0].getScore();
    }

    private long hitCount(String index, String term) {
        return client().prepareSearch(index)
            .setQuery(QueryBuilders.matchQuery(CONTENT_FIELD, term))
            .setSize(0)
            .get()
            .getHits()
            .getTotalHits()
            .value();
    }

    /**
     * Isolation is enforced by the plugin's FILTER clause (same as DLS): the restricted docs are invisible even
     * though they physically share the index.
     */
    public void testIsolationIsEnforcedByThePlugin() throws Exception {
        buildCorpus();
        buildVisibleOnlyIndex();
        VisibleSubsetPlugin.ARMED.set(true);

        // The restricted term occurs in 200 non-visible docs + the 1 visible sample doc; the plugin's filter
        // hides the 200, so only the visible sample doc is returned.
        assertEquals("only the visible sample doc matches the restricted term", 1L, hitCount(INDEX, RESTRICTED_TERM));
        // The "absent" term occurs only in the visible sample doc (that is how it gets a score), so it too
        // returns exactly that one doc -- and never any restricted doc.
        assertEquals("only the visible sample doc matches the absent term", 1L, hitCount(INDEX, ABSENT_TERM));
    }

    /**
     * Leak-free AND still ranked: through the seam the restricted-only term scores the same as an absent term
     * (leak-free), and that score equals the score against a physical visible-only index (real BM25 over the
     * visible subset, not a flat constant).
     */
    public void testScoringIsVisibleSubsetOnlyAndStillRanked() throws Exception {
        buildCorpus();
        buildVisibleOnlyIndex();
        VisibleSubsetPlugin.ARMED.set(true);

        float restrictedScore = sampleScore(INDEX, RESTRICTED_TERM);
        float absentScore = sampleScore(INDEX, ABSENT_TERM);
        float physicalScore = sampleScore(VISIBLE_INDEX, RESTRICTED_TERM);

        assertTrue("sample doc found for restricted term through the plugin", restrictedScore > 0f);
        assertTrue("sample doc found for absent term through the plugin", absentScore > 0f);

        // Leak-free: the 200 non-visible docs carrying the restricted term never enter its IDF, so it is
        // indistinguishable from a term that exists nowhere.
        assertEquals(
            "restricted-only term must score the same as an absent term (no whole-shard df leak)",
            absentScore,
            restrictedScore,
            0.0001f
        );

        // Still ranked: the score equals real BM25 computed over just the visible docs. This is the property the
        // constant_score bridge cannot provide -- there every visible hit would score a flat 1.0.
        assertEquals(
            "score must equal real BM25 over a physical visible-only index (ranking preserved, not flattened)",
            physicalScore,
            restrictedScore,
            0.01f
        );
    }
}

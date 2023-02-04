/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.identity;

import org.junit.Before;
import org.opensearch.client.Request;
import org.opensearch.client.Response;
import org.opensearch.identity.rest.IdentityRestConstants;
import org.opensearch.test.OpenSearchIntegTestCase;

import java.util.List;
import java.util.Map;

import static org.opensearch.test.rest.OpenSearchRestTestCase.entityAsMap;

/**
 * Tests REST API for users against local cluster
 */
@OpenSearchIntegTestCase.ClusterScope(scope = OpenSearchIntegTestCase.Scope.TEST, numDataNodes = 0)
public class UserCrudIT extends HttpSmokeTestCaseWithIdentity {
    private static final String ENDPOINT = IdentityRestConstants.IDENTITY_REST_API_REQUEST_PREFIX;;

    public UserCrudIT() {}

    @Before
    public void startClusterWithIdentityIndex() throws Exception {
        startNodesWithIdentityIndex();
    }

    @SuppressWarnings("unchecked")
    public void testUsersRestApi() throws Exception {

        final Map<String, String> emptyMap = Map.of();
        final List<String> emptyList = List.of();

        String username = "test-create";

        // Create a user
        String createSuccessMessage = username + " created successfully.";
        Request createRequest = new Request("PUT", ENDPOINT + "/users/" + username);
        createRequest.setJsonEntity("{ \"password\" : \"test\" }\n");
        Response response = getRestClient().performRequest(createRequest);
        assertEquals(response.getStatusLine().getStatusCode(), 200);
        Map<String, Object> createResponse = entityAsMap(response);
        List<Map<String, Object>> usersCreated = (List<Map<String, Object>>) createResponse.get("users");
        assertEquals(usersCreated.size(), 1);
        assertEquals(usersCreated.get(0).get("successful"), true);
        assertEquals(usersCreated.get(0).get("username"), username);
        assertEquals(usersCreated.get(0).get("message"), createSuccessMessage);

        // Update a user
        String updateSuccessMessage = username + " updated successfully.";
        Request updateRequest = new Request("PUT", ENDPOINT + "/users/" + username);
        updateRequest.setJsonEntity("{ \"password\" : \"test\" }\n");
        response = getRestClient().performRequest(updateRequest);
        assertEquals(response.getStatusLine().getStatusCode(), 200);
        Map<String, Object> updateResponse = entityAsMap(response);
        List<Map<String, Object>> usersUpdated = (List<Map<String, Object>>) updateResponse.get("users");
        assertEquals(usersUpdated.size(), 1);
        assertEquals(usersUpdated.get(0).get("successful"), true);
        assertEquals(usersUpdated.get(0).get("username"), username);
        assertEquals(usersUpdated.get(0).get("message"), updateSuccessMessage);

        // GET a user
        Request getRequest = new Request("GET", ENDPOINT + "/users/" + username);
        response = getRestClient().performRequest(getRequest);
        assertEquals(response.getStatusLine().getStatusCode(), 200);
        Map<String, Object> getResponse = entityAsMap(response);
        Map<String, String> user = (Map<String, String>) getResponse.get("user");
        assertEquals(user.get("username"), username);
        assertEquals(user.get("attributes"), emptyMap);
        assertEquals(user.get("permissions"), emptyList);

        // GET all users
        Request mGetRequest = new Request("GET", ENDPOINT + "/users");
        response = getRestClient().performRequest(mGetRequest);
        assertEquals(response.getStatusLine().getStatusCode(), 200);
        Map<String, Object> mGetResponse = entityAsMap(response);
        List<Map<String, Object>> users = (List<Map<String, Object>>) mGetResponse.get("users");
        assertEquals(users.size(), 2);
        assertEquals(users.get(0).get("username"), "admin");
        assertEquals(users.get(0).get("attributes"), emptyMap);
        assertEquals(users.get(0).get("permissions"), emptyList);
        assertEquals(users.get(1).get("username"), username);
        assertEquals(users.get(1).get("attributes"), emptyMap);
        assertEquals(users.get(1).get("permissions"), emptyList);

        // DELETE a user
        String deletedMessage = username + " deleted successfully.";
        Request deleteRequest = new Request("DELETE", ENDPOINT + "/users/" + username);
        response = getRestClient().performRequest(deleteRequest);
        assertEquals(response.getStatusLine().getStatusCode(), 200);
        Map<String, Object> deleteResponse = entityAsMap(response);
        List<Map<String, Object>> deletedUsers = (List<Map<String, Object>>) deleteResponse.get("users");
        assertEquals(deletedUsers.size(), 1);
        assertEquals(deletedUsers.get(0).get("successful"), true);
        assertEquals(deletedUsers.get(0).get("message"), deletedMessage);
    }

}

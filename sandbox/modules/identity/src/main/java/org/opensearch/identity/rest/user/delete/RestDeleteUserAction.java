/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.identity.rest.user.delete;

import com.fasterxml.jackson.core.JsonParseException;
import com.fasterxml.jackson.databind.JsonNode;
import org.opensearch.client.node.NodeClient;
import org.opensearch.identity.DefaultObjectMapper;
import org.opensearch.identity.rest.IdentityRestConstants;
import org.opensearch.identity.utils.ErrorType;
import org.opensearch.rest.BaseRestHandler;
import org.opensearch.rest.RestChannel;
import org.opensearch.rest.RestRequest;
import org.opensearch.rest.action.RestStatusToXContentListener;

import java.io.IOException;
import java.util.List;

import static java.util.Arrays.asList;
import static org.opensearch.identity.utils.RoutesHelper.addRoutesPrefix;
import static org.opensearch.rest.RestRequest.Method.DELETE;

/**
 * Rest action for deleting a user
 */
public class RestDeleteUserAction extends BaseRestHandler {

    @Override
    public String getName() {
        return IdentityRestConstants.IDENTITY_DELETE_USER_ACTION;
    }

    /**
     * Rest request handler for deleting a user
     *
     * @param request the request to execute
     * @param client  client for executing actions on the local node
     * @return the action to be executed See {@link #handleRequest(RestRequest, RestChannel, NodeClient) for more}
     *
     * ````
     * Sample Request:
     * curl -XDELETE http://new-user:password@localhost:9200/_identity/api/users/test
     *
     *
     * Sample Response
     *
     * {
     *   "users": [
     *     {
     *       "successful": true,
     *       "message": "test deleted successfully."
     *     }
     *   ]
     * }
     * ````
     */
    @Override
    public RestChannelConsumer prepareRequest(RestRequest request, NodeClient client) {
        String username = request.param("name");
        DeleteUserRequest deleteUserRequest = new DeleteUserRequest(username);

        return channel -> client.doExecute(DeleteUserAction.INSTANCE, deleteUserRequest, new RestStatusToXContentListener<>(channel));
    }

    /**
     * Routes to be registered for this action
     *
     * @return the unmodifiable list of routes to be registered
     */
    @Override
    public List<Route> routes() {
        // e.g. return value "_identity/api/users/test"
        return addRoutesPrefix(asList(new Route(DELETE, "/users/{name}")));
    }

}

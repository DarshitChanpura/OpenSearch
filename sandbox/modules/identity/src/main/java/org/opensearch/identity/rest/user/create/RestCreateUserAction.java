/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.identity.rest.user.create;

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
import static org.opensearch.rest.RestRequest.Method.PUT;

/**
 * Rest action for creating a user
 *
 * /users/{user} rest request action to create a user
 *
 * @opensearch.api
 */
public class RestCreateUserAction extends BaseRestHandler {

    @Override
    public String getName() {
        return IdentityRestConstants.IDENTITY_CREATE_USER_ACTION;
    }

    /**
     * Rest request handler for creating a new user
     * @param request the request to execute
     * @param client  client for executing actions on the local node
     * @return the action to be executed See {@link #handleRequest(RestRequest, RestChannel, NodeClient) for more}
     * @throws IOException if errors encountered when parsing from XContent
     */
    @Override
    public RestChannelConsumer prepareRequest(RestRequest request, NodeClient client) throws IOException {
        String username = request.param("name");

        // Parsing request body using DefaultObjectMapper
        JsonNode contentAsNode;
        try {
            contentAsNode = DefaultObjectMapper.readTree(request.content().utf8ToString());
        } catch (JsonParseException e) {
            throw new IllegalArgumentException(ErrorType.BODY_NOT_PARSEABLE.getMessage() + "CREATE");
        }
        String password = contentAsNode.get("password").asText();

        CreateUserRequest createUserRequest = new CreateUserRequest(username, password);

        // TODO: check if this bypass to directly doExecute is okay.
        // TODO: Ideally, this should be registered as `createUser` request in Client.java and AbstractClient.java
        // TODO: see if you can add to RequestConverters.java to follow convention
        return channel -> client.doExecute(CreateUserAction.INSTANCE, createUserRequest, new RestStatusToXContentListener<>(channel));
    }

    /**
     * Routes to be registered for this action
     * @return the unmodifiable list of routes to be registered
     */
    @Override
    public List<Route> routes() {
        // e.g. return value "_identity/api/users/test"
        return addRoutesPrefix(asList(new Route(PUT, "/users/{name}")));
    }

}

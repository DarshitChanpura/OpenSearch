/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.identity.rest.user.get;

import org.opensearch.action.ActionResponse;
import org.opensearch.common.ParseField;
import org.opensearch.common.io.stream.StreamInput;
import org.opensearch.common.io.stream.StreamOutput;
import org.opensearch.common.xcontent.ConstructingObjectParser;
import org.opensearch.common.xcontent.StatusToXContentObject;
import org.opensearch.common.xcontent.XContentBuilder;
import org.opensearch.common.xcontent.XContentParser;
import org.opensearch.rest.RestStatus;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import static org.opensearch.common.xcontent.ConstructingObjectParser.constructorArg;
import static org.opensearch.rest.RestStatus.NOT_FOUND;
import static org.opensearch.rest.RestStatus.OK;

/**
 * Response class for create user request
 * Contains list of responses of each user creation request
 */
public class GetUserResponse extends ActionResponse implements StatusToXContentObject {

    // TODO: revisit this class
    private final List<GetUserResponseInfo> createUserResults;

    public GetUserResponse(List<GetUserResponseInfo> createUserResults) {
        this.createUserResults = createUserResults;
    }

    public GetUserResponse(StreamInput in) throws IOException {
        super(in);
        int size = in.readVInt();
        createUserResults = new ArrayList<>();
        for (int i = 0; i < size; i++) {
            createUserResults.add(new GetUserResponseInfo(in));
        }

    }

    public List<GetUserResponseInfo> getCreateUserResults() {
        return createUserResults;
    }

    /**
     * @return Whether the attempt to Create a user was successful
     */
    @Override
    public RestStatus status() {
        if (createUserResults.isEmpty()) return NOT_FOUND;
        return OK;
    }

    @Override
    public void writeTo(StreamOutput out) throws IOException {
        out.writeVInt(createUserResults.size());
        for (GetUserResponseInfo createUserResults : createUserResults) {
            createUserResults.writeTo(out);
        }
    }

    @Override
    public XContentBuilder toXContent(XContentBuilder builder, Params params) throws IOException {
        builder.startObject();
        builder.startArray("users");
        for (GetUserResponseInfo response : createUserResults) {
            response.toXContent(builder, params);
        }
        builder.endArray();
        builder.endObject();
        return builder;
    }

    private static final ConstructingObjectParser<GetUserResponse, Void> PARSER = new ConstructingObjectParser<>(
        "create_user_response",
        true,
        (Object[] parsedObjects) -> {
            @SuppressWarnings("unchecked")
            List<GetUserResponseInfo> createUserResponseInfoList = (List<GetUserResponseInfo>) parsedObjects[0];
            return new GetUserResponse(createUserResponseInfoList);
        }
    );
    static {
        PARSER.declareObjectArray(constructorArg(), GetUserResponseInfo.PARSER, new ParseField("users"));
    }

    public static GetUserResponse fromXContent(XContentParser parser) throws IOException {
        return PARSER.parse(parser, null);
    }

}
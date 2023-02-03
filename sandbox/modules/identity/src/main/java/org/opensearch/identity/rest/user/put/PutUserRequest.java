/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 */

package org.opensearch.identity.rest.user.put;

import org.opensearch.action.ActionRequest;
import org.opensearch.action.ActionRequestValidationException;
import org.opensearch.common.io.stream.StreamInput;
import org.opensearch.common.io.stream.StreamOutput;
import org.opensearch.common.xcontent.ToXContent;
import org.opensearch.common.xcontent.ToXContentObject;
import org.opensearch.common.xcontent.XContentBuilder;
import org.opensearch.common.xcontent.XContentParser;

import java.io.IOException;

import static org.opensearch.action.ValidateActions.addValidationError;

/**
 * Request to create or update a user
 */
public class PutUserRequest extends ActionRequest implements ToXContentObject {

    private String username;
    private String password;

    public PutUserRequest(StreamInput in) throws IOException {
        super(in);
        username = in.readString();
        password = in.readString();
    }

    public PutUserRequest(String username, String password) {
        this.username = username;
        this.password = password;
    }

    public PutUserRequest() {}

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    @Override
    public ActionRequestValidationException validate() {
        ActionRequestValidationException validationException = null;
        if (username == null) { // TODO: cehck the condition once
            validationException = addValidationError("No username specified", validationException);
        } else if (password == null) {
            validationException = addValidationError("No password specified", validationException);
        }
        return validationException;
    }

    @Override
    public void writeTo(StreamOutput out) throws IOException {
        super.writeTo(out);
        out.writeString(username);
        out.writeString(password);
    }

    @Override
    public XContentBuilder toXContent(XContentBuilder builder, ToXContent.Params params) throws IOException {
        builder.startObject();
        builder.value(username);
        builder.value(password);
        builder.endObject();
        return builder;
    }

    // TODO: See if this method is actually needed, or the alternative of using DefaultObjectMapper is a better approach
    public void fromXContent(XContentParser parser) throws IOException {

        if (parser.nextToken() != XContentParser.Token.START_OBJECT) {
            throw new IllegalArgumentException("Malformed content, must start with an object");
        } else {
            XContentParser.Token token;
            String currentFieldName = null;
            while ((token = parser.nextToken()) != XContentParser.Token.END_OBJECT) {
                if (token == XContentParser.Token.FIELD_NAME) {
                    currentFieldName = parser.currentName();
                } else if ("password".equals(currentFieldName)) {

                    if (token.isValue() == false) {
                        throw new IllegalArgumentException(); // TODO: check the message to be returned
                    }

                    // add any validation checks here

                    password = parser.text();

                }
                // add all other fields to be parsed from body
                else {
                    throw new IllegalArgumentException(
                        "Unknown parameter [" + currentFieldName + "] in request body or parameter is of the wrong type[" + token + "] "
                    );
                }
            }
        }
    }

}
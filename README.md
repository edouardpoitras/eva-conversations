Conversations
=============

An Eva plugin that stores interaction data in MongoDB.

Also enables follow-up questions from users.

## Installation

Can be easily installed through the Web UI by using [Web UI Plugins](https://github.com/edouardpoitras/eva-web-ui-plugins).

Alternatively, add `conversations` to your `eva.conf` file in the `enabled_plugins` option list and restart Eva.

## Usage

Once enabled, Eva will keep track of all interactions between the clients.
This plugin also enables the idea of a follow-up question (if other plugins support it).

See the [Web UI Conversations](https://github.com/edouardpoitras/eva-web-ui-conversations) plugin in order to browse all interactions stored by this plugin.

## Developers

This plugin will attach a `conversation` object to every interaction.
It can be accessed during the interaction phase via the context object:

    @gossip.register('eva.interaction')
    def interaction(context):
        # Simply close the conversations (no follow-up question).
        context.conversation.close()

It can also be accessed in a new trigger fired for follow-up queries/commands (see below).

#### Triggers

This plugin actives a new gossip trigger called `eva.conversations.follow_up`.

This trigger is called at the very beginning of the interaction phase (priority of 100), and allows plugins to take a first stab at responding to the user.

It's up to the individual plugins to decide when to take advantage of this trigger.

Here's a simple example that will tell the user when the current conversation began:

    @gossip.register('eva.conversations.follow_up')
    def interaction(plugin, context):
        # If this is a follow-up question for the 'my_plugin' plugin.
        if plugin == 'my_plugin':
            if context.contains('conversation') && \
            (context.contains('opened') or \
             context.contains('started')):
                context.set_output_text('This conversation started at %s' %context.conversation.opened)

The plugin parameter in this trigger is populated with the plugin id of the plugin that last used the `context.set_output_text()` method.
This means the same plugin will most likely receive another opportunity for a follow-up until the conversation expires, or a plugin explicitly closes the conversation.

#### Objects

The Conversation object is a mongoengine.Document object with the following fields:

    opened = mongoengine.fields.DateTimeField(default=datetime.datetime.now) # The date and time this converstaion was opened.
    interactions = mongoengine.fields.EmbeddedDocumentListField(Interaction) # The list of Interactions in this conversation.
    closed = mongoengine.fields.DateTimeField() # The date and time this conversation was closed.
    follow_up_plugin = None # The follow-up plugin ID to set on the next interaction.
    meta = {'collection': 'conversations'} # The MongoDB collection to store conversation data.

Use the `context.conversation.get_current_interaction()` method to get the conversation's current interaction.

Use the `context.conversation.close()` method to close out the current conversation once you've responded with `context.set_output_text()` and you know there will be no follow-up query/command from the user.

The Interaction object is a mongoengine.EmbeddedDocument with the following fields:

    id = mongoengine.fields.ObjectIdField() # The ID of this interaction object.
    opened = mongoengine.fields.DateTimeField(default=datetime.datetime.now) # The date and time this interaction was opened.
    input_text = mongoengine.fields.StringField() # The text received from the client.
    input_audio = mongoengine.fields.FileField() # The audio data received from the client.
    input_text_alterations = mongoengine.fields.EmbeddedDocumentListField(TextAlteration) # Alterations performed by plugins on the input_text.
    output_text = mongoengine.fields.StringField() # The output text to be sent to the clients as a response.
    output_audio = mongoengine.fields.FileField() # The output audio to be sent to the clients as a response.
    output_text_alterations = mongoengine.fields.EmbeddedDocumentListField(TextAlteration) # Alterations performed by the plugins on the output_text.
    responding_plugin = mongoengine.fields.StringField() # The plugin id that responded to this query/command.
    closed = mongoengine.fields.DateTimeField() # The date and time this interaction was closed.

Adding/removing, opening/closing interactions will be handled automatically by this plugins.
Adding input/output text alterations will also be handled automatically when using the context object to `context.set_input_text()` or `context.set_output_text()`.

Each TextAlteration object is a mongoengine.EmbeddedDocument object with the following fields:

    new_text = mongoengine.fields.StringField() # The new text that replaced the old interaction text.
    plugin = mongoengine.fields.StringField() # The plugin that performed the text alteration.

Please check out the [mongoengine documentation](http://docs.mongoengine.org/) for more details on these object types.

## Configuration

Default configurations can be changed by adding a `conversations.conf` file in your plugin configuration path (can be configured in `eva.conf`, but usually `~/eva/configs`).

To get an idea of what configuration options are available, you can take a look at the `conversations.conf.spec` file in this repository, or use the [Web UI Plugins](https://github.com/edouardpoitras/eva-web-ui-plugins) plugin and view them at `/plugins/configuration/conversations`.

Here is a breakdown of the available options:

    conversation_expires
        Type: Integer
        Default: 60
        The number of seconds of inactivity before a conversation automatically closes.
        This will 'reset' the conversation and the next interaction will not be considered for a follow-up query/command trigger.

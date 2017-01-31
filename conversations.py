"""
Stores Eva conversation data in MongoDB and enable plugins to handle follow-up
queries/commands from the clients.
"""

import datetime
from io import BytesIO
from bson.objectid import ObjectId
import mongoengine
import gossip
from eva import log
from eva import conf

mongoengine.connect(db=conf['mongodb']['database'],
                    host=conf['mongodb']['host'],
                    port=conf['mongodb']['port'],
                    username=conf['mongodb']['username'],
                    password=conf['mongodb']['password'])

@gossip.register('eva.pre_interaction', provides=['conversations'])
def pre_interaction(context):
    """
    This function is registered to the `eva.pre_interaction` trigger and will
    execute before an interaction is initiated.

    This is where the :class:`Conversation` object is attached to the context.
    Expired conversations will be closed and new conversations will be created
    in this function. A new :class:`Interaction` is always added to the
    conversation at the end of the function.

    :param context: The context object created for this interaction.
    :type context: :class:`eva.context.EvaContext`
    """
    # Load the current conversation.
    context.conversation = get_current_conversation()
    if context.conversation is not None:
        # Close the conversation if past expiration.
        expires = conf['plugins']['conversations']['config']['conversation_expires']
        now = datetime.datetime.now()
        current_interaction = context.conversation.get_current_interaction()
        last_activity = current_interaction.closed
        if last_activity is not None and now - last_activity > datetime.timedelta(seconds=expires):
            log.info('Conversation expired - older than %s seconds' %expires)
            context.conversation.close()
        else:
            # Conversation not closed, potentially a follow-up query.
            context.conversation.follow_up_plugin_id = current_interaction.responding_plugin_id
    # It's possible that a plugin has closed the conversation explicitly.
    # Also check if the conversation is set to closed.
    if context.conversation is None or context.conversation.closed is not None:
        log.info('Creating new conversation')
        gossip.trigger('eva.conversations.pre_new_conversation')
        context.conversation = Conversation()
        # Save so that if someone calls get_current_conversation they get this one.
        context.conversation.save()
        gossip.trigger('eva.conversations.post_new_conversation')
    # Create a new interaction.
    log.info('Creating new interaction')
    context.conversation.create_interaction(context)

@gossip.register('eva.interaction', priority=100)
def interaction(context):
    """
    This function is registered to the `eva.interaction` trigger with a priority
    of 100. It will most likely be the first hook to run during the interaction
    phase.

    The `eva.conversations.follow_up` trigger is fired in this function to allow
    plugins to perform actions on follow-up questions from the user.

    :param context: The context object created for this interaction.
    :type context: :class:`eva.context.EvaContext`
    """
    # Allow potential follow-up queries to be handled first (hence high priority).
    plugin_id = context.conversation.follow_up_plugin_id
    gossip.trigger('eva.conversations.follow_up', plugin_id=plugin_id, context=context)

@gossip.register('eva.post_interaction', provides=['conversations'])
def post_interaction(context):
    """
    This function is registered to the `eva.post_interaction` trigger and is
    solely used to close the current :class:`Interaction`.

    :param context: The context object created for this interaction.
    :type context: :class:`eva.context.EvaContext`
    """
    context.conversation.get_current_interaction().close(context)

@gossip.register('eva.pre_set_input_text')
def pre_set_input_text(text, plugin_id, context):
    """
    This function is registered to the `eva.pre_set_input_text` trigger. It is
    used to attach the input text alterations to the :class:`Interaction`
    object.

    :param text: The input text to be set.
    :type text: string
    :param plugin_id: The plugin that is setting the input text.
    :type plugin_id: string
    :param context: The context object created for this interaction.
    :type context: :class:`eva.context.EvaContext`
    """
    inter = context.conversation.get_current_interaction()
    inter.add_input_alteration(text, plugin_id)
    context.conversation.save()

@gossip.register('eva.pre_set_output_text')
def pre_set_output_text(text, responding, plugin_id, context):
    """
    This function is registered to the `eva.pre_set_output_text` trigger. It is
    used to attach the output text alterations to the :class:`Interaction`
    object.

    :param text: The output text to be set.
    :type text: string
    :param responding: Whether or not this new output text is meant to be the
        response to the query from the user.
        This could be set to False if the plugin wishes to simply alter an
        existing response that was compiled by another plugin during the
        interaction.
    :type responding: boolean
    :param plugin_id: The plugin that is setting the input text.
    :type plugin_id: string
    :param context: The context object created for this interaction.
    :type context: :class:`eva.context.EvaContext`
    """
    inter = context.conversation.get_current_interaction()
    inter.add_output_alteration(text, plugin_id, responding)
    context.conversation.save()

def get_current_conversation():
    """
    A helper function to get the current active conversation.

    Will find the first conversation that does not have the `closed` field set,
    ordered by ObjectID DESC.

    :return: The current active conversation object.
    :rtype: :class:`Conversation`
    """
    return Conversation.objects(closed__exists=False).order_by('-id').first() #pylint: disable=E1101

class TextAlteration(mongoengine.EmbeddedDocument):
    """
    Simply :class:`mongoengine.EmbeddedDocument` object used to track the input
    and output text alterations throughout Eva interactions.

    Fields:
        new_text - :class:`mongoengine.fields.StringField`
            The new text that is being set.
        plugin_id - :class:`mongoengine.fields.StringField`
            The plugin ID of the plugin that is performing the alteration.
    """
    new_text = mongoengine.fields.StringField()
    plugin_id = mongoengine.fields.StringField()

class Interaction(mongoengine.EmbeddedDocument):
    """
    :class:`mongoengine.EmbeddedDocument` object used to track Eva interactions.

    Fields:
        id - :class:`mongoengine.fields.ObjectIdField`
            The unique identifier for this interaction.
        opened - :class:`mongoengine.fields.DateTimeField` (Default=datetime.datetime.now)
            The datetime that the interaction was created.
        input_text - :class:`mongoengine.fields.StringField`
            The query/command text used when starting this interaction.
        input_audio - :class:`mongoengine.fields.FileField`
            The query/command audio data for this interaction.
        input_text_alterations -
            :class:`mongoengine.fields.EmbeddedDocumentListField`
            A list of :class:`TextAlteration` objects for the input_text.
        output_text - :class:`mongoengine.fields.StringField`
            The response text used for this interaction.
        output_audio - :class:`mongoengine.fields.FileField`
            The response audio data for this interaction.
        output_text_alterations -
            :class:`mongoengine.fields.EmbeddedDocumentListField`
            A list of :class:`TextAlteration` objects for the output_text.
        responding_plugin_id - :class:`mongoengine.fields.StringField`
            The plugin_id of the plugin who has responded to this interaction's
            query/command.
        closed - :class:`mongoengine.fields.DateTimeField`
            The closing datetime for this interaction.
    """
    id = mongoengine.fields.ObjectIdField() #pylint: disable=C0103
    opened = mongoengine.fields.DateTimeField(default=datetime.datetime.now)
    input_text = mongoengine.fields.StringField()
    input_audio = mongoengine.fields.FileField()
    input_text_alterations = mongoengine.fields.EmbeddedDocumentListField(TextAlteration)
    output_text = mongoengine.fields.StringField()
    output_audio = mongoengine.fields.FileField()
    output_text_alterations = mongoengine.fields.EmbeddedDocumentListField(TextAlteration)
    responding_plugin_id = mongoengine.fields.StringField()
    closed = mongoengine.fields.DateTimeField()

    def parse_interaction_data(self, data):
        """
        Helper method to parse the interaction data submitted by the client and
        store it in this object.

        This method is currently not being used. Instead, the conversation object
        manually creates the interaction and an accompanying input_text_alteration.

        :TODO: Actually use this in order to store input_audio.

        :param data: The interaction data received from the clients.
            Typically a dict containing the 'input_text' and 'input_audio' keys.
        :type data: dict
        """
        self.input_text = data.get('input_text', None)
        input_audio = data.get('input_audio', None)
        if input_audio and 'audio' in input_audio and 'content_type' in input_audio:
            self.set_input_audio(input_audio)

    def set_input_audio(self, data):
        """
        Helper method to store the input audio in this interaction object.

        :param data: The interaction data received from the clients.
            Expects a dict with the 'audio' and 'content_type' keys.
        :type data: dict
        """
        audio = BytesIO(data['audio'])
        content_type = data['content_type']
        self.input_audio.put(audio, content_type=content_type)

    def add_input_alteration(self, new_text, plugin_id):
        """
        A helper method that adds a new input alteration to the interaction.

        :param new_text: The new text for this alteration.
        :type new_text: string
        :param plugin_id: The plugin ID of the plugin that is performing this
            alteration.
        :type plugin_id: string
        """
        self.input_text_alterations.create(new_text=new_text, plugin_id=plugin_id) #pylint: disable=E1101

    def add_output_alteration(self, new_text, plugin_id, responding=True):
        """
        A helper method that adds a new output alteration to the interaction.

        :param new_text: The new text for this alteration.
        :type new_text: string
        :param plugin_id: The plugin ID of the plugin that is performing this
            alteration.
        :type plugin_id: string
        :param responding: Whether or not this is the primary responding plugin.
            If this is set to False, the `responding_plugin_id` field will not
            be set to the specified plugin_id.
        :type responding: boolean
        """
        self.output_text_alterations.create(new_text=new_text, plugin_id=plugin_id) #pylint: disable=E1101
        if responding:
            # Set the responding plugin.
            self.responding_plugin_id = plugin_id

    def close(self, context):
        """
        A helper method that closes the current interaction.

        Fires the `eva.conversations.pre_close_interaction` and
        `eva.conversations.post_close_interaction` triggers.

        Takes care of populating the output_text, output_audio, and closed
        fields.

        :param context: The context object created for this interaction.
        :type context: :class:`eva.context.EvaContext`
        """
        gossip.trigger('eva.conversations.pre_close_interaction', context=context)
        self.output_text = context.get_output_text()
        self.set_output_audio(context)
        self.closed = datetime.datetime.now()
        context.conversation.save()
        gossip.trigger('eva.conversations.post_close_interaction', context=context)

    def set_output_audio(self, context):
        """
        A helper method to store the interaction's output_audio based on the
        context object provided.

        :param context: The context object created for this interaction.
        :type context: :class:`eva.context.EvaContext`
        """
        audio = BytesIO(context.get_output_audio())
        content_type = context.get_output_audio_content_type()
        self.output_audio.put(audio, content_type=content_type)

class Conversation(mongoengine.Document):
    """
    :class:`mongoengine.Document` object used to track Eva conversations.

    Fields:
        opened - :class:`mongoengine.fields.DateTimeField` (Default=datetime.datetime.now)
            The datetime that the conversation was created.
        interactions - :class:`mongoengine.fields.EmbeddedDocumentListField`
            The list of :class:`Interaction` objects tied to this conversation.
        closed - :class:`mongoengine.fields.DateTimeField`
            The datetime that the conversation was closed.
        follow_up_plugin_id - string
            The plugin ID of the plugin that will be used for the follow-up
            trigger on the next interaction.
        meta - dict
            Specifies that we're using the 'conversations' collection to store
            conversation objects in the database.
    """
    opened = mongoengine.fields.DateTimeField(default=datetime.datetime.now)
    interactions = mongoengine.fields.EmbeddedDocumentListField(Interaction)
    closed = mongoengine.fields.DateTimeField()
    follow_up_plugin_id = None
    meta = {'collection': 'conversations'}

    def get_current_interaction(self):
        """
        Helper method that returns the current :class:`Interaction` (the last
        one in the database).
        """
        return self.interactions[-1] #pylint: disable=E1136

    def create_interaction(self, context):
        """
        Helper method that creates a new interaction based on the context
        specified. Will add the first input alteration based on the context's
        input_text.

        Will fire the `eva.conversations.pre_create_interaction` and
        `eva.conversations.post_create_interaction` triggers.

        :param context: The context object created for the current interaction.
        :type context: :class:`eva.context.EvaContext`
        """
        gossip.trigger('eva.conversations.pre_create_interaction', context=context)
        text = context.get_input_text()
        inter = self.interactions.create(id=ObjectId(), input_text=text) #pylint: disable=E1101
        inter.add_input_alteration(text, None)
        self.save()
        gossip.trigger('eva.conversations.post_create_interaction', context=context)

    def close(self):
        """
        Helper method to close the current conversation.

        Will fire the `eva.conversations.pre_close_conversation` and
        `eva.conversations.post_close_conversation` triggers.
        """
        gossip.trigger('eva.conversations.pre_close_conversation')
        self.closed = datetime.datetime.now()
        self.save()
        gossip.trigger('eva.conversations.post_close_conversation')

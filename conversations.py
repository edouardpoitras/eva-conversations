import datetime
import gossip
from io import BytesIO
from bson.objectid import ObjectId
import mongoengine
from eva import log
from eva import conf

username = conf['mongodb']['username']
password = conf['mongodb']['password']
host = conf['mongodb']['host']
port = conf['mongodb']['port']
db = conf['mongodb']['database']
mongoengine.connect(db=db, host=host, port=port, username=username, password=password)

@gossip.register('eva.pre_interaction', provides=['conversations'])
def pre_interaction(context):
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
            context.conversation.follow_up_plugin = current_interaction.responding_plugin
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
    # Allow potential follow-up queries to be handled first (hence high priority).
    plugin = context.conversation.follow_up_plugin
    gossip.trigger('eva.conversations.follow_up', plugin=plugin, context=context)

@gossip.register('eva.post_interaction', provides=['conversations'])
def post_interaction(context):
    context.conversation.get_current_interaction().close(context)

@gossip.register('eva.pre_set_input_text')
def pre_set_input_text(text, plugin, context):
    interaction = context.conversation.get_current_interaction()
    interaction.add_input_alteration(text, plugin)
    context.conversation.save()

@gossip.register('eva.pre_set_output_text')
def pre_set_output_text(text, responding, plugin, context):
    interaction = context.conversation.get_current_interaction()
    interaction.add_output_alteration(text, plugin, responding)
    context.conversation.save()

def get_current_conversation():
    return Conversation.objects(closed__exists=False).order_by('-id').first()

class TextAlteration(mongoengine.EmbeddedDocument):
    new_text = mongoengine.fields.StringField()
    plugin = mongoengine.fields.StringField()

class Interaction(mongoengine.EmbeddedDocument):
    id = mongoengine.fields.ObjectIdField()
    opened = mongoengine.fields.DateTimeField(default=datetime.datetime.now)
    input_text = mongoengine.fields.StringField()
    input_audio = mongoengine.fields.FileField()
    input_text_alterations = mongoengine.fields.EmbeddedDocumentListField(TextAlteration)
    output_text = mongoengine.fields.StringField()
    output_audio = mongoengine.fields.FileField()
    output_text_alterations = mongoengine.fields.EmbeddedDocumentListField(TextAlteration)
    responding_plugin = mongoengine.fields.StringField()
    closed = mongoengine.fields.DateTimeField()

    def parse_interaction_data(self, data):
        self.input_text = data.get('input_text', None)
        input_audio = data.get('input_audio', None)
        if input_audio and 'audio' in input_audio and 'content_type' in input_audio:
            self.set_input_audio(data)

    def set_input_audio(self, data):
        audio = BytesIO(data['audio'])
        content_type = data['content_type']
        self.input_audio.put(audio, content_type=content_type)

    def add_input_alteration(self, text, plugin):
        self.input_text_alterations.create(new_text=text, plugin=plugin)

    def add_output_alteration(self, text, plugin, responding=True):
        self.output_text_alterations.create(new_text=text, plugin=plugin)
        if responding:
            # Set the responding plugin.
            self.responding_plugin = plugin

    def close(self, context):
        gossip.trigger('eva.conversations.pre_close_interaction', context=context)
        self.output_text = context.get_output_text()
        self.set_output_audio(context)
        self.closed = datetime.datetime.now()
        context.conversation.save()
        gossip.trigger('eva.conversations.post_close_interaction', context=context)

    def set_output_audio(self, context):
        audio = BytesIO(context.get_output_audio())
        content_type = context.get_output_audio_content_type()
        self.output_audio.put(audio, content_type=content_type)

class Conversation(mongoengine.Document):
    opened = mongoengine.fields.DateTimeField(default=datetime.datetime.now)
    interactions = mongoengine.fields.EmbeddedDocumentListField(Interaction)
    closed = mongoengine.fields.DateTimeField()
    follow_up_plugin = None
    meta = {'collection': 'conversations'}

    def get_current_interaction(self):
        return self.interactions[-1]

    def create_interaction(self, context):
        gossip.trigger('eva.conversations.pre_create_interaction', context=context)
        text = context.get_input_text()
        interaction = self.interactions.create(id=ObjectId(), input_text=text)
        interaction.add_input_alteration(text, None)
        self.save()
        gossip.trigger('eva.conversations.post_create_interaction', context=context)

    def close(self):
        gossip.trigger('eva.conversations.pre_close_conversation')
        self.closed = datetime.datetime.now()
        self.save()
        gossip.trigger('eva.conversations.post_close_conversation')
